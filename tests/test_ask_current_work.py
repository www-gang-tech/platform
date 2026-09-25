"""Current-work questions: "what is Daniel working on this week?"

This used to be generic retrieval for "Daniel", newest first — and the newest
documents that mention a person are calendar invitations, newsletters, and
system alerts. The answer summarized an inbox. These tests pin the repaired
behavior: a CURRENT_WORK route that reads the same assigned work ownership
does, keeps what is open and recent, never lets bulk mail or invitations
become work, attaches decisions and meetings only as context, and makes at
most one local-model call whose output is validated against the packet.

Everything runs against a temporary GANG_HOME, on a fixed clock. The network
is wired to fail if touched.
"""

import json
import os
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core.access import Principal, PrincipalDirectory
from core.ask import ConversationOptions, ConversationService
from core.ask import assignments as assignments_module
from core.ask import current_work as current_work_module
from core.ask import deterministic as deterministic_module
from core.ask import intent as intent_module
from core.ask.synthesis import SynthesisError
from core.entities import EntityService
from core.private_index import PrivateKnowledgeIndex

from test_ask_ownership import ExplodingDirector, ExplodingPlanner, ExplodingSynthesizer
from test_conversation import write_markdown


#: Thursday. The week runs Monday 2026-09-21 to Sunday 2026-09-27.
TODAY = date(2026, 9, 24)

SCHEDULE_ID = "01a0bf00-0000-7000-a000-00000000d001"
MINUTES_ID = "01a0bf00-0000-7000-a000-00000000d002"
OLD_MINUTES_ID = "01a0bf00-0000-7000-a000-00000000d003"
NEWSLETTER_ID = "01a0bf00-0000-7000-a000-00000000d004"
ALERT_ID = "01a0bf00-0000-7000-a000-00000000d005"
PARTNER_INVITE_ID = "01a0bf00-0000-7000-a000-00000000d006"
REVIEW_INVITE_ID = "01a0bf00-0000-7000-a000-00000000d007"

BULK_IDS = {NEWSLETTER_ID, ALERT_ID, PARTNER_INVITE_ID, REVIEW_INVITE_ID}

SHOPIFY = "Confirm Shopify build requirements and required OK-RM assets"
QI = "Resubmit the WPC Qi certification with four PTx subsystems"
UPC = "Procure permanent UPC code registration"
COST_SHEET = "Obtain the detailed Creative Engineering cost sheet and component breakdown"


def _mail(document_id, title, day, sender):
    return {
        "id": document_id,
        "type": "knowledge",
        "source_type": "gmail-thread",
        "title": title,
        "visibility": "private",
        "status": "active",
        "content_trust": "untrusted",
        "source_id": f"gmail-thread_{document_id[-4:]}",
        "created": day,
        "updated": day,
        "from": sender,
    }


def _meeting(document_id, title, day):
    return {
        "id": document_id,
        "type": "meeting",
        "source_type": "meeting",
        "title": title,
        "visibility": "private",
        "status": "active",
        "content_trust": "untrusted",
        "source_id": f"meeting_{document_id[-4:]}",
        "created": day,
        "updated": day,
    }


class LocalSynthesizer:
    """A loopback model. Records every request; answers with ``respond``."""

    provider_name = "ollama"
    model = "local-test"
    has_credentials = True
    is_remote = False

    def __init__(self, respond):
        self.respond = respond
        self.requests = []
        self.telemetry = {}

    def complete_json(self, request, *, purpose):
        self.requests.append(request)
        self.telemetry = {"provider": self.provider_name, "model": self.model, "status": "ok"}
        return self.respond(_packet_items(request))

    def synthesize(self, context, **kwargs):
        raise AssertionError("Current work builds its own request; generic synthesis must not run.")

    def build_request(self, context):
        raise AssertionError("Current work builds its own request; generic synthesis must not run.")


class FailingLocalSynthesizer(LocalSynthesizer):
    def complete_json(self, request, *, purpose):
        self.requests.append(request)
        self.telemetry = {"provider": self.provider_name, "model": self.model, "status": "timeout"}
        raise SynthesisError("local model timed out")


class RemoteSynthesizer(ExplodingSynthesizer):
    """A remote provider. Current work must never send it anything."""

    provider_name = "anthropic"
    is_remote = True

    def complete_json(self, request, *, purpose):
        raise AssertionError("Current work must never call a remote provider.")


def _packet_items(request):
    content = request["messages"][0]["content"]
    return json.loads(content.split("DATA:\n", 1)[1])["items"]


def _ids_for(items, *needles):
    return [item["id"] for item in items if any(needle in item["task"] for needle in needles)]


class CurrentWorkTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        credentials = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
        credentials.start()
        self.addCleanup(credentials.stop)
        network = mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected provider network call."),
        )
        network.start()
        self.addCleanup(network.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)

        # A schedule email: owner fields, deadlines, statuses. Open, overdue,
        # due this week, done, far off, and someone else's.
        write_markdown(
            self.home / "vault/emails/schedule.md",
            _mail(SCHEDULE_ID, "GANG Schedule — Due Soon (2026-09-21)", "2026-09-21",
                  "Daniel Hirunrusme <daniel@gang.example>"),
            "From: Daniel Hirunrusme <daniel@gang.example> - To: daniel@gang.example, frank@gang.example\n"
            f"1. {SHOPIFY} Owner: Daniel | Due: 2026-09-04 (OVERDUE) | Status: in progress\n"
            f"2. {QI} Owner: Daniel | Due: 2026-09-20 | Status: in progress\n"
            f"3. {UPC} Owner: Daniel | Due: 2026-09-25 | Status: not started\n"
            "4. Renew the trademark filing Owner: Daniel | Due: 2026-08-01 | Status: done\n"
            "5. Hire the project manager Owner: Daniel | Due: 2026-11-20 | Status: not started\n"
            "6. Escalate the BOM delay to Creative Engineering Owner: Frank | Due: 2026-09-05 | Status: in progress\n",
        )
        # This week's board notes: an action item and a decision about owned work.
        write_markdown(
            self.home / "vault/meetings/board-29.md",
            _meeting(MINUTES_ID, "Executive Board Meeting 29 Notes", "2026-09-22"),
            "Attendees: Daniel Hirunrusme, Frank Godchaux\n\n"
            f"Daniel will obtain the detailed Creative Engineering cost sheet and component breakdown. "
            "Frank will send the prototype photographs to Eliro.\n\n"
            "Decision\n\nWPC Qi certification resubmission will include the four PTx subsystems.\n",
        )
        # Six weeks old: open when written, not current now.
        write_markdown(
            self.home / "vault/meetings/board-18.md",
            _meeting(OLD_MINUTES_ID, "Meeting 18 Notes", "2026-08-10"),
            "Daniel will schedule a conversation with Tony about the advisory board.\n",
        )
        # A newsletter and a system alert, each worded like a task for Daniel.
        write_markdown(
            self.home / "vault/emails/newsletter.md",
            _mail(NEWSLETTER_ID, "MoMA Members: This Week at the Museum", "2026-09-23",
                  "MoMA <newsletter@moma.example>"),
            "From: MoMA <newsletter@moma.example> - To: daniel@gang.example\n"
            "@Daniel: RSVP for the members preview of the new exhibition. "
            "Unsubscribe | Manage your email preferences\n",
        )
        write_markdown(
            self.home / "vault/emails/alert.md",
            _mail(ALERT_ID, "[ALERT] Project “Lehmann Maupin” has used 100% of its included Assets",
                  "2026-09-23", "Frame <alerts@frame.example>"),
            "From: Frame <alerts@frame.example> - To: daniel@gang.example\n"
            "Upgrade the Lehmann Maupin workspace storage plan Owner: Daniel | Due: 2026-09-25 | Status: open. "
            "You're receiving this because you are a workspace admin.\n",
        )
        # Two invitations: a recurring partner sync, and a review of real work.
        write_markdown(
            self.home / "vault/emails/partner-invite.md",
            _mail(PARTNER_INVITE_ID,
                  "Updated invitation: GANG - Eliro Inc @ Weekly from 1pm to 2pm on Thursday (EDT) (daniel@gang.example)",
                  "2026-09-23", "Google Calendar <calendar-notification@google.com>"),
            "Daniel Hirunrusme is invited to GANG - Eliro Inc. Invitation from Google Calendar.\n",
        )
        write_markdown(
            self.home / "vault/emails/review-invite.md",
            _mail(REVIEW_INVITE_ID,
                  "Invitation: WPC Qi certification resubmission review @ Fri Sep 25, 2026 11am - 12pm (EDT) (daniel@gang.example)",
                  "2026-09-23", "Google Calendar <calendar-notification@google.com>"),
            "Daniel Hirunrusme is invited. Invitation from Google Calendar.\n",
        )

    # ------------------------------------------------------------- helpers

    def seed(self):
        service = EntityService(root_path=self.root, private_home=self.home)
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.example"])
        frank = service.create("person", "Frank Godchaux", aliases=["Frank"], emails=["frank@gang.example"])
        PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()
        return {"daniel": daniel, "frank": frank}

    def service(self, synthesizer=None):
        return ConversationService(
            root_path=self.root,
            private_home=self.home,
            clock=TODAY,
            synthesizer=synthesizer or ExplodingSynthesizer(),
            query_planner=ExplodingPlanner(),
            director=ExplodingDirector(),
        )

    def ask(self, question, *, use_ai=False, synthesizer=None, principal_name=None, local_only=False):
        service = self.service(synthesizer)
        return service.converse(
            question,
            session=service.start(),
            options=ConversationOptions(
                use_ai=use_ai,
                use_cache=False,
                persist=False,
                show_research=True,
                principal_name=principal_name,
                local_only=local_only or None,
                local_only_requested=local_only,
            ),
        )

    def work(self, result):
        records = (result.get("structured_records") or {}).get(current_work_module.CURRENT_WORK_KEY) or [{}]
        return records[0]

    def tasks(self, result):
        return {item["task"]: item for item in self.work(result).get("items") or []}


# ============================================================ intent routing


class CurrentWorkRoutingTests(unittest.TestCase):
    def test_current_work_phrasings_route_with_their_subject(self):
        cases = {
            "What is Daniel working on currently this week?": "Daniel",
            "what is Daniel working on?": "Daniel",
            "what is Daniel working on this week?": "Daniel",
            "what's Daniel focused on right now?": "Daniel",
            "what's on Daniel's plate?": "Daniel",
            "what is Frank currently working on?": "Frank",
            "what am I working on this week?": "I",
            "what are my current priorities?": "my",
            "What is Frank Godchaux working on?": "Frank Godchaux",
        }
        for question, subject in cases.items():
            with self.subTest(question=question):
                intent = intent_module.infer_intent(question)
                self.assertEqual(intent.policy, intent_module.CURRENT_WORK)
                self.assertEqual(intent.subject, subject)
                self.assertTrue(intent.wants_current_work)
                self.assertFalse(intent.wants_assignments)

    def test_neighbouring_questions_keep_their_own_routes(self):
        self.assertEqual(intent_module.infer_intent("what does Daniel need to do?").policy, intent_module.OWNERSHIP)
        self.assertEqual(intent_module.infer_intent("what are Daniel's tasks?").policy, intent_module.OWNERSHIP)
        # Topic-scoped and historical questions are not "what now".
        self.assertEqual(intent_module.infer_intent("What is Frank working on with Eliro?").policy, intent_module.LOOKUP)
        self.assertEqual(intent_module.infer_intent("what has Daniel worked on?").policy, intent_module.LOOKUP)
        self.assertEqual(intent_module.infer_intent("what should I focus on this week?").policy, intent_module.ADVISORY)
        for question in ("what are you working on?", "what are we working on?", "what is it working on?"):
            with self.subTest(question=question):
                self.assertNotEqual(intent_module.infer_intent(question).policy, intent_module.CURRENT_WORK)

    def test_current_work_routes_to_its_own_tool_without_an_evidence_window(self):
        intent = intent_module.infer_intent("what is Daniel working on this week?")

        routes = deterministic_module.capability_routes(
            "what is Daniel working on this week?", _Plan(), intent, today=TODAY
        )

        self.assertEqual([route["tool"] for route in routes], ["find_current_work"])
        self.assertEqual(routes[0]["key"], current_work_module.CURRENT_WORK_KEY)
        self.assertEqual(routes[0]["arguments"], {"person": "Daniel", "today": "2026-09-24"})


class _Plan:
    text_queries = ["daniel", "working"]
    entity_ids = []
    query = "what is Daniel working on this week?"

    class date_range:
        start = "2026-09-21"
        end = "2026-09-24"


# ================================================================ selection


def _assignment(task, *, status="", deadline="", stated="2026-09-22", document_id="doc-1", basis="owner-field"):
    return assignments_module.Assignment(
        task=task,
        owner="Daniel",
        basis=basis,
        deadline=deadline,
        status=assignments_module.normalize_status(status),
        status_text=status,
        document_ids=[document_id],
        titles=["Schedule"],
        date=stated,
    )


class SelectionTests(unittest.TestCase):
    def select(self, *items, classes=None):
        return current_work_module.select(items, today=TODAY, source_classes=classes or {})

    def test_open_recent_work_is_current_and_closed_stale_or_far_off_work_is_not(self):
        selection = self.select(
            _assignment("Overdue but still in progress", status="in progress", deadline="2026-09-04"),
            _assignment("Due Friday", status="not started", deadline="2026-09-25"),
            _assignment("Finished already", status="done", deadline="2026-09-20"),
            _assignment("Nobody has mentioned since August", status="in progress", stated="2026-08-10"),
            _assignment("Not started and due in November", status="not started", deadline="2026-11-20"),
            _assignment("Under way though due in November", status="in progress", deadline="2026-11-20"),
        )

        tasks = [item["task"] for item in selection.items]
        self.assertEqual(
            tasks,
            ["Overdue but still in progress", "Due Friday", "Under way though due in November"],
        )
        self.assertEqual(selection.counts(), {"closed": 1, "stale": 1, "later": 1, "omitted": 0})
        overdue, friday, _ = selection.items
        self.assertEqual(overdue["timing"], current_work_module.OVERDUE)
        self.assertEqual(friday["timing"], current_work_module.DUE_THIS_WEEK)

    def test_work_stated_only_in_bulk_mail_is_never_current(self):
        selection = self.select(
            _assignment("RSVP for the members preview", document_id="newsletter"),
            _assignment("Upgrade the storage plan", document_id="alert", status="open"),
            classes={"newsletter": "bulk", "alert": "bulk"},
        )
        self.assertEqual(selection.items, [])

    def test_the_packet_is_bounded(self):
        many = [_assignment(f"Distinct task number {index} for the launch", deadline="2026-09-25") for index in range(30)]
        selection = current_work_module.select(many, today=TODAY)
        self.assertEqual(len(selection.items), current_work_module.MAX_ITEMS)
        self.assertEqual(selection.omitted, 30 - current_work_module.MAX_ITEMS)
        self.assertEqual([item["id"] for item in selection.items[:2]], ["w1", "w2"])

    def test_week_runs_monday_to_sunday(self):
        self.assertEqual(current_work_module.week_of(TODAY), (date(2026, 9, 21), date(2026, 9, 27)))

    def test_schedule_deadlines_are_read_as_dates(self):
        self.assertEqual(assignments_module.deadline_date("Sep. 18 — Noon", "2026-09-16"), date(2026, 9, 18))
        self.assertEqual(assignments_module.deadline_date("2026-09-04 (OVERDUE)", ""), date(2026, 9, 4))
        self.assertEqual(assignments_module.deadline_date("Before Sep 18 meeting", "2026-09-16"), date(2026, 9, 18))
        self.assertEqual(assignments_module.deadline_date("Jan 10", "2026-12-01"), date(2027, 1, 10))
        self.assertIsNone(assignments_module.deadline_date("Near term", "2026-09-16"))
        self.assertIsNone(assignments_module.deadline_date("Sep 18", ""))


class ScheduleReaderTests(unittest.TestCase):
    """The owner-field reader on a flattened schedule of record."""

    BODY = (
        "Exception / Carry-Forward Check Confirm closure: "
        "[Vendor] Meet with CE to close outstanding info requests — scheduled end Sep 18; baseline status In progress "
        "— Owner: Frank/Daniel "
        "[Certification] WPC Qi certification (QI-27832) — resubmit with 4 PTx subsystems — scheduled end Sep 20; "
        "baseline status In progress — Owner: Daniel "
        "[Business] Project Management Hire — scheduled end Oct 20; baseline status Not started — Owner: Frank/Daniel/Eliro "
        "[Marketing] Postcard mailing to signups — scheduled end Oct 15; baseline status Not started — Owner: Creative Engineering"
    )

    def gather(self):
        row = {"document_id": "gantt", "title": "Gantt", "body": self.BODY, "updated": "2026-09-18"}
        person = assignments_module.person_from("Daniel Hirunrusme", aliases=["Daniel"], resolved=True)
        return {item.task: item for item in assignments_module.gather([row], person)}

    def test_a_row_does_not_begin_with_the_previous_rows_owners(self):
        tasks = self.gather()
        self.assertIn("[Certification] WPC Qi certification (QI-27832) — resubmit with 4 PTx subsystems", tasks)
        self.assertFalse(any(task.startswith("Frank") for task in tasks))
        self.assertNotIn("[Marketing] Postcard mailing to signups", tasks)

    def test_the_schedule_note_becomes_deadline_and_status(self):
        tasks = self.gather()
        qi = tasks["[Certification] WPC Qi certification (QI-27832) — resubmit with 4 PTx subsystems"]
        self.assertEqual((qi.deadline, qi.status), ("Sep 20", assignments_module.IN_PROGRESS))
        hire = tasks["[Business] Project Management Hire"]
        self.assertEqual((hire.deadline, hire.status), ("Oct 20", assignments_module.OPEN))

    def test_not_started_is_open_not_in_progress(self):
        self.assertEqual(assignments_module.normalize_status("Not started"), assignments_module.OPEN)
        self.assertEqual(assignments_module.normalize_status("Started"), assignments_module.IN_PROGRESS)


# =============================================================== validation


class ValidationTests(unittest.TestCase):
    WORK = {
        "items": [
            {"id": "w1", "task": QI, "category": "Certification", "status": "in-progress", "status_text": "in progress",
             "deadline": "2026-09-20", "due": "2026-09-20", "timing": "overdue", "co_owners": [],
             "titles": ["Schedule"], "citations": [1], "decisions": [], "meetings": []},
            {"id": "w2", "task": UPC, "category": "", "status": "open", "status_text": "not started",
             "deadline": "2026-09-25", "due": "2026-09-25", "timing": "due-this-week", "co_owners": [],
             "titles": ["Schedule"], "citations": [1], "decisions": [], "meetings": []},
            {"id": "w3", "task": COST_SHEET, "category": "", "status": "", "status_text": "",
             "deadline": "", "due": "", "timing": "", "co_owners": [],
             "titles": ["Board notes"], "citations": [2], "decisions": [], "meetings": []},
        ]
    }

    def test_grounded_workstreams_survive_with_code_derived_citations_and_details(self):
        checked = current_work_module.validate(
            {"workstreams": [
                {"title": "WPC Qi certification", "summary": "Resubmitting the certification with four PTx subsystems.",
                 "item_ids": ["w1"]},
                {"title": "UPC and Creative Engineering costs", "summary": "Procure the UPC registration and obtain the cost sheet.",
                 "item_ids": ["w2", "w3"]},
            ]},
            self.WORK,
        )
        self.assertEqual([stream["title"] for stream in checked.workstreams],
                         ["WPC Qi certification", "UPC and Creative Engineering costs"])
        self.assertEqual(checked.workstreams[0]["citations"], [1])
        self.assertEqual(checked.workstreams[1]["citations"], [1, 2])
        self.assertEqual(checked.workstreams[0]["details"], "in progress; overdue — was due Sep 20")
        self.assertEqual(checked.workstreams[1]["details"], "open; due Sep 25")

    def test_invented_work_unknown_ids_and_stray_numbers_are_rejected(self):
        checked = current_work_module.validate(
            {"workstreams": [
                {"title": "Series B fundraising", "summary": "Pitching investors for the Series B round.", "item_ids": ["w1"]},
                {"title": "UPC registration", "summary": "Procure the UPC code.", "item_ids": ["w9"]},
                {"title": "WPC Qi certification", "summary": "Resubmit certification with 12 subsystems.", "item_ids": ["w1"]},
                {"title": "", "summary": "Untitled.", "item_ids": ["w2"]},
            ]},
            self.WORK,
        )
        self.assertEqual(checked.workstreams, [])
        self.assertEqual(
            [entry["reason"] for entry in checked.rejected],
            [
                "uses words its items do not",
                "names no unclaimed item in the packet",
                "states a number its items do not",
                "no title",
            ],
        )

    def test_an_item_belongs_to_one_workstream_and_there_are_at_most_eight(self):
        streams = [{"title": "WPC Qi certification", "summary": "", "item_ids": ["w1"]}] * 2
        checked = current_work_module.validate({"workstreams": streams}, self.WORK)
        self.assertEqual(len(checked.workstreams), 1)

        many = {"items": [
            {**self.WORK["items"][1], "id": f"w{index}", "citations": [1]} for index in range(1, 12)
        ]}
        checked = current_work_module.validate(
            {"workstreams": [{"title": "UPC registration", "summary": "", "item_ids": [f"w{index}"]} for index in range(1, 12)]},
            many,
        )
        self.assertEqual(len(checked.workstreams), current_work_module.MAX_WORKSTREAMS)

    def test_a_response_without_workstreams_is_rejected(self):
        self.assertEqual(current_work_module.validate({"answer": "Daniel is busy."}, self.WORK).workstreams, [])
        self.assertEqual(current_work_module.validate("not json", self.WORK).workstreams, [])


# ================================================================== answers


class CurrentWorkAnswerTests(CurrentWorkTestCase):
    QUESTION = "What is Daniel working on currently this week?"

    def test_the_answer_is_built_from_assigned_work_not_recent_mentions(self):
        self.seed()

        result = self.ask(self.QUESTION)

        self.assertEqual(result["intent"]["policy"], intent_module.CURRENT_WORK)
        self.assertEqual([entry["tool"] for entry in result["research"]["trace"]], ["find_current_work"])
        self.assertEqual(result["synthesis"]["reason"], current_work_module.DETERMINISTIC_REASON)
        self.assertEqual(result["provider_calls"], [])
        answer = result["answer"]
        self.assertTrue(answer.startswith("Daniel — current work (week of Sep 21–Sep 27)"))
        for task in (SHOPIFY, QI, UPC, COST_SHEET):
            self.assertIn(task, answer)
        # Nothing from the newsletter, the alert, or the partner-sync invitation.
        for absent in ("MoMA", "RSVP", "Lehmann Maupin", "storage plan", "Eliro Inc", "GANG - Eliro"):
            self.assertNotIn(absent, answer)
        cited = {source["document_id"] for source in result["sources"]}
        self.assertFalse(cited & (BULK_IDS - {REVIEW_INVITE_ID}))

    def test_bulk_mail_would_otherwise_read_as_assignments(self):
        """The filter is not vacuous: the task list reader alone accepts these."""
        seeded = self.seed()
        service = self.service()
        rows = service.retriever.documents([NEWSLETTER_ID, ALERT_ID])
        person = assignments_module.person_from("Daniel")
        self.assertEqual(len(assignments_module.gather(rows, person)), 2)

        tasks = self.tasks(self.ask(self.QUESTION))
        self.assertFalse(any("RSVP" in task or "storage plan" in task for task in tasks))
        self.assertTrue(seeded)

    def test_closed_stale_and_far_off_work_is_left_out_and_counted(self):
        self.seed()

        result = self.ask(self.QUESTION)
        tasks = self.tasks(result)

        self.assertNotIn("Renew the trademark filing", tasks)
        self.assertNotIn("Hire the project manager", tasks)
        self.assertFalse(any("Tony" in task for task in tasks))
        self.assertFalse(any("BOM delay" in task for task in tasks))
        excluded = self.work(result)["excluded"]
        self.assertEqual((excluded["closed"], excluded["stale"], excluded["later"]), (1, 1, 1))
        self.assertGreaterEqual(excluded["bulk_documents"], 3)

    def test_overdue_work_that_is_still_open_is_included_and_marked(self):
        self.seed()

        result = self.ask(self.QUESTION)

        self.assertEqual(self.tasks(result)[SHOPIFY]["timing"], current_work_module.OVERDUE)
        self.assertIn(f"{SHOPIFY} — in progress; overdue — was due Sep 4", result["answer"])
        self.assertIn(f"{UPC} — not started; due Sep 25", result["answer"])

    def test_decisions_and_connected_meetings_are_context_never_work(self):
        self.seed()

        result = self.ask(self.QUESTION)
        answer = result["answer"]

        qi = self.tasks(result)[QI]
        self.assertEqual([entry["name"] for entry in qi["meetings"]], ["WPC Qi certification resubmission review"])
        self.assertEqual(
            [entry["text"] for entry in qi["decisions"]],
            ["WPC Qi certification resubmission will include the four PTx subsystems."],
        )
        self.assertIn("related meeting: WPC Qi certification resubmission review", answer)
        self.assertIn("related decision: WPC Qi certification resubmission will include the four PTx subsystems.", answer)
        # A meeting is never an item of its own.
        self.assertFalse(any("review" in task.casefold() for task in self.tasks(result)))

    def test_every_line_is_cited(self):
        self.seed()

        result = self.ask(self.QUESTION)

        for line in result["answer"].splitlines():
            if line.lstrip().startswith(("- ", "related ")):
                self.assertRegex(line, r"\[\d+\]$", line)
        self.assertTrue(result["claims"])
        self.assertTrue(all(claim["citations"] for claim in result["claims"]))

    def test_the_evidence_overlaps_the_task_list(self):
        self.seed()

        current = self.ask(self.QUESTION)
        tasks = self.ask("what does Daniel need to do?")

        self.assertEqual(tasks["intent"]["policy"], intent_module.OWNERSHIP)
        self.assertTrue(tasks["answer"].startswith("Daniel — current action items"))
        assigned = {
            document_id
            for item in (tasks["structured_records"]["assignments"][0]["assignments"])
            for document_id in item["document_ids"]
        }
        work_sources = {
            document_id for item in self.work(current)["items"] for document_id in item["document_ids"]
        }
        self.assertTrue(work_sources)
        self.assertLessEqual(work_sources, assigned)

    def test_first_person_uses_the_principal(self):
        self.seed()

        mine = self.ask("what am I working on this week?", principal_name="Daniel")
        named = self.ask(self.QUESTION)

        self.assertEqual(set(self.tasks(mine)), set(self.tasks(named)))

    def test_first_person_without_a_principal_is_not_guessed(self):
        self.seed()

        result = self.ask("what am I working on this week?")

        self.assertTrue(result["insufficient_evidence"])
        self.assertIn("can't tell who", result["answer"])

    def test_someone_with_nothing_current_gets_a_scoped_absence(self):
        self.seed()

        result = self.ask("what is Dana working on?")

        self.assertTrue(result["insufficient_evidence"])
        self.assertIn("no open, recently stated work explicitly assigned to Dana", result["answer"])


# =============================================================== synthesis


class CurrentWorkSynthesisTests(CurrentWorkTestCase):
    QUESTION = "What is Daniel working on currently this week?"

    def grouping(self, items):
        return {"workstreams": [
            {"title": "WPC Qi certification", "summary": "Resubmit the certification with four PTx subsystems.",
             "item_ids": _ids_for(items, "WPC Qi")},
            {"title": "Shopify and OK-RM assets", "summary": "Confirm the Shopify build requirements and OK-RM assets.",
             "item_ids": _ids_for(items, "Shopify")},
            {"title": "UPC and Creative Engineering costs", "summary": "Procure the UPC registration and obtain the cost sheet.",
             "item_ids": _ids_for(items, "UPC", "cost sheet")},
        ]}

    def test_one_local_call_clusters_the_packet_into_cited_workstreams(self):
        self.seed()
        local = LocalSynthesizer(self.grouping)

        result = self.ask(self.QUESTION, use_ai=True, synthesizer=local)

        self.assertEqual(len(local.requests), 1)
        self.assertEqual(len(result["provider_calls"]), 1)
        self.assertEqual(result["synthesis"]["mode"], "ai")
        self.assertEqual(result["synthesis"]["reason"], current_work_module.CURRENT_WORK_REASON)
        self.assertEqual(result["planner"], "deterministic")
        answer = result["answer"]
        self.assertIn(
            "- WPC Qi certification: Resubmit the certification with four PTx subsystems. — in progress; "
            "overdue — was due Sep 20",
            answer,
        )
        self.assertIn("- UPC and Creative Engineering costs:", answer)
        self.assertEqual([claim["type"] for claim in result["claims"]], ["synthesis"] * 3)
        self.assertTrue(all(claim["citations"] for claim in result["claims"]))

    def test_the_model_sees_only_the_structured_packet(self):
        self.seed()
        local = LocalSynthesizer(self.grouping)

        self.ask(self.QUESTION, use_ai=True, synthesizer=local)

        request = local.requests[0]
        text = request["system"] + request["messages"][0]["content"]
        for absent in ("MoMA", "RSVP", "Lehmann", "Eliro Inc", "Attendees", "Frank will send", "Unsubscribe"):
            self.assertNotIn(absent, text)
        allowed = {"id", "task", "category", "status", "deadline", "timing", "shared_with",
                   "related_decisions", "related_meetings"}
        for item in _packet_items(request):
            self.assertLessEqual(set(item), allowed)
        self.assertEqual(request["format"]["required"], ["workstreams"])

    def test_invented_workstreams_fall_back_to_the_grouped_list(self):
        self.seed()
        local = LocalSynthesizer(lambda items: {"workstreams": [
            {"title": "Series B fundraising", "summary": "Pitching investors.", "item_ids": [items[0]["id"]]},
            {"title": "Hiring a CTO", "summary": "Interviewing candidates.", "item_ids": ["w99"]},
        ]})

        result = self.ask(self.QUESTION, use_ai=True, synthesizer=local)

        self.assertEqual(len(local.requests), 1)
        self.assertEqual(result["synthesis"]["mode"], "deterministic")
        self.assertEqual(result["synthesis"]["fallback"], "local-synthesis-rejected")
        self.assertNotIn("Series B", result["answer"])
        self.assertNotIn("CTO", result["answer"])
        self.assertIn(QI, result["answer"])
        self.assertIn("did not survive validation", result["uncertainty"])

    def test_uncovered_pressing_work_is_listed_and_the_rest_counted(self):
        self.seed()
        local = LocalSynthesizer(lambda items: {"workstreams": [
            {"title": "WPC Qi certification", "summary": "", "item_ids": _ids_for(items, "WPC Qi")},
        ]})

        result = self.ask(self.QUESTION, use_ai=True, synthesizer=local)

        self.assertEqual(result["synthesis"]["mode"], "ai")
        self.assertIn("Also overdue or due this week (2):", result["answer"])
        self.assertIn(f"- {SHOPIFY}", result["answer"])
        self.assertIn(f"- {UPC}", result["answer"])
        # Undated, so summarized away rather than listed — but counted.
        self.assertNotIn(COST_SHEET, result["answer"])
        self.assertIn("1 more open item(s) not shown.", result["answer"])

    def test_a_failed_local_model_falls_back_without_trying_anything_else(self):
        self.seed()
        local = FailingLocalSynthesizer(self.grouping)

        result = self.ask(self.QUESTION, use_ai=True, synthesizer=local, local_only=True)

        self.assertEqual(len(local.requests), 1)
        self.assertEqual(result["synthesis"]["mode"], "deterministic")
        self.assertEqual(result["synthesis"]["fallback"], "local-synthesis-unavailable")
        self.assertEqual([call["status"] for call in result["provider_calls"]], ["timeout"])
        self.assertIn(QI, result["answer"])
        self.assertIn("no remote provider was tried", result["uncertainty"])

    def test_a_remote_provider_is_never_sent_the_packet(self):
        self.seed()

        result = self.ask(self.QUESTION, use_ai=True, synthesizer=RemoteSynthesizer())

        self.assertEqual(result["provider_calls"], [])
        self.assertEqual(result["synthesis"]["mode"], "deterministic")
        self.assertEqual(result["synthesis"]["fallback"], "no-local-model")
        self.assertIn(QI, result["answer"])

    def test_no_ai_answers_from_the_same_packet(self):
        self.seed()

        result = self.ask(self.QUESTION, use_ai=False, synthesizer=LocalSynthesizer(self.grouping))

        self.assertEqual(result["synthesis"]["fallback"], "ai-disabled")
        self.assertEqual(result["provider_calls"], [])


class CliCurrentWorkTests(CurrentWorkTestCase):
    def test_cli_answers_a_first_person_current_work_question(self):
        self.seed()
        PrincipalDirectory(self.home / "access/principals.yml").save(
            [Principal(principal_id="daniel", display_name="Daniel")]
        )

        with mock.patch("core.ask.conversation.temporal_today", return_value=TODAY):
            output = CliRunner().invoke(
                gang_cli.cli,
                ["ask", "what am I working on this week?", "--no-ai"],
                env={"GANG_HOME": str(self.home), "ANTHROPIC_API_KEY": ""},
                catch_exceptions=False,
            ).output

        self.assertIn("Daniel — current work (week of Sep 21–Sep 27)", output)
        self.assertIn(QI, output)
        self.assertNotIn("MoMA", output)
        self.assertIn("answered deterministically: deterministic-current-work", output)


if __name__ == "__main__":
    unittest.main()
