"""Ownership questions: "what does Daniel need to do?" returns Daniel's tasks.

This used to work. Commit 52c57be gave definition questions a deterministic
short-circuit to the canonical-description lookup, and "what does X need to
do?" matched the definition shape "what does X … do" — so a task-list question
retrieved nothing but authored identity, found none, and answered "I couldn't
find evidence". These tests pin the repaired boundary: an ownership route ahead
of definition, decision, and listing; explicit assignments only; one line per
task; status honoured; and no model anywhere on the path.

Everything runs against a temporary GANG_HOME. The network and every provider
are wired to fail if touched.
"""

import os
import sys
import textwrap
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
from core.ask import deterministic as deterministic_module
from core.ask import intent as intent_module
from core.entities import EntityService
from core.private_index import PrivateKnowledgeIndex

from test_ask_stage3 import run_node_stage3_check
from test_conversation import write_markdown


SCHEDULE_ID = "01a0bf00-0000-7000-a000-00000000c001"
MINUTES_ID = "01a0bf00-0000-7000-a000-00000000c002"
FOLLOWUP_ID = "01a0bf00-0000-7000-a000-00000000c003"
ENRICHED_ID = "01a0bf00-0000-7000-a000-00000000c004"
OLD_SCHEDULE_ID = "01a0bf00-0000-7000-a000-00000000c005"

NO_EVIDENCE = "No documents in the private corpus matched this question."


class ExplodingSynthesizer:
    """A provider that fails the test if the answer path ever reaches it."""

    provider_name = "exploding"
    model = "exploding-model"
    has_credentials = True

    def synthesize(self, context, **kwargs):
        raise AssertionError("A deterministic ownership answer must not call a synthesis model.")

    def build_request(self, context):
        raise AssertionError("A deterministic ownership answer must not build a model request.")


class ExplodingPlanner:
    provider_name = "exploding"
    model = "exploding-model"
    has_credentials = True

    def propose(self, question, catalog):
        raise AssertionError("A deterministic ownership answer must not call a planning model.")


class ExplodingDirector:
    provider_name = "exploding"
    model = "exploding-model"
    has_credentials = True

    def decide(self, *args, **kwargs):
        raise AssertionError("A deterministic ownership answer must not call a research model.")


class OwnershipTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        credentials = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
        credentials.start()
        self.addCleanup(credentials.stop)
        network = mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected provider network call on a deterministic path."),
        )
        network.start()
        self.addCleanup(network.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)

        # A daily schedule email: owner fields with due dates and statuses.
        write_markdown(
            self.home / "vault/emails/schedule.md",
            {
                "id": SCHEDULE_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "GANG Schedule — Due Soon (2026-09-21)",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_schedule",
                "created": "2026-09-21",
                "updated": "2026-09-21",
            },
            "From: Daniel Hirunrusme <daniel@gang.example> - To: daniel@gang.example, frank@gang.example\n"
            "Open tasks are due today, imminent, or overdue:\n"
            "1. Confirm Shopify build requirements and required OK-RM assets Owner: Daniel | "
            "Due: 2026-09-04 (OVERDUE) | Status: in progress Tips: pull the asset list from the build scope.\n"
            "2. Formally escalate BOM delay to Creative Engineering Owner: Frank | "
            "Due: 2026-09-05 (OVERDUE) | Status: in progress\n"
            "3. Renew the trademark filing Owner: Daniel | Due: 2026-08-01 | Status: done\n"
            "4. Order the PCB art proof Owner: Daniel | Due: 2026-09-12 | Status: done\n",
        )
        # An older copy of the same schedule, before the proof was ordered.
        write_markdown(
            self.home / "vault/emails/schedule-old.md",
            {
                "id": OLD_SCHEDULE_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "GANG Schedule — Due Soon (2026-09-08)",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_schedule_old",
                "created": "2026-09-08",
                "updated": "2026-09-08",
            },
            "Open tasks:\n"
            "1. Order the PCB art proof Owner: Daniel | Due: 2026-09-12 | Status: in progress\n",
        )
        # Meeting minutes: an attendee list, prose assignments, a non-assignment
        # mention, and a flattened owner table.
        write_markdown(
            self.home / "vault/meetings/board-28.md",
            {
                "id": MINUTES_ID,
                "type": "meeting",
                "source_type": "meeting",
                "title": "Executive Board Meeting 28 Notes",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "meeting_board_28",
                "created": "2026-09-16",
                "updated": "2026-09-16",
            },
            "Attendees: Daniel Hirunrusme, Frank Godchaux, Dana Reyes\n\n"
            "Daniel will confirm the UPC registration source and purchase the UPC package by Friday. "
            "Dana noted that the enclosure review moved to next week. "
            "Frank will send the prototype photographs to Eliro. "
            "The group agreed to meet with Dana to discuss packaging.\n\n"
            "Deliverables / Action Items Owner Deliverable Deadline / Timing Status "
            "Daniel Draft integrated Master Gantt Chart through mid-2027 Sep. 18 — Noon In Progress "
            "Frank / Daniel Meet with Creative Engineering and close information requests Before Sep. 18 meeting Open "
            "Frank Include Dana on future factory-selection calls Ongoing Open "
            "------------------------------\n",
        )
        # A follow-up restating one of the meeting's assignments.
        write_markdown(
            self.home / "vault/emails/followup.md",
            {
                "id": FOLLOWUP_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Recap and next steps",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_followup",
                "created": "2026-09-18",
                "updated": "2026-09-18",
            },
            "Hi all, a quick recap. Daniel will confirm the UPC registration source and purchase "
            "the UPC package. Thanks Daniel for the notes.\n",
        )
        # Derived action items with explicit owners, one of them superseded.
        write_markdown(
            self.home / "vault/documents/certification-plan.md",
            {
                "id": ENRICHED_ID,
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Qi certification plan",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "drive-file_cert_plan",
                "created": "2026-09-19",
                "updated": "2026-09-19",
                "action_items": [
                    {"task": "Draft the Qi certification checklist", "owner": "Frank"},
                    {"task": "Book the Shenzhen factory visit", "owner": "Daniel", "status": "superseded"},
                ],
            },
            "Certification plan for the Qi2 enclosure.\n",
        )

    # ------------------------------------------------------------- helpers

    def seed(self):
        """People with no authored descriptions. Daniel has no short alias."""
        service = EntityService(root_path=self.root, private_home=self.home)
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.example"])
        frank = service.create("person", "Frank Godchaux", aliases=["Frank"], emails=["frank@gang.example"])
        dana = service.create("person", "Dana Reyes", aliases=["Dana"])
        for document_id in (MINUTES_ID, SCHEDULE_ID):
            service.add_mention(document_id, frank.id, excerpt="Frank")
        service.add_mention(MINUTES_ID, dana.id, excerpt="Dana Reyes")
        PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()
        return {"daniel": daniel, "frank": frank, "dana": dana}

    def service(self, clock=None):
        return ConversationService(
            root_path=self.root,
            private_home=self.home,
            clock=clock,
            synthesizer=ExplodingSynthesizer(),
            query_planner=ExplodingPlanner(),
            director=ExplodingDirector(),
        )

    def ask(self, question, *, use_ai=True, principal_name=None, clock=None):
        service = self.service(clock)
        return service.converse(
            question,
            session=service.start(),
            options=ConversationOptions(
                use_ai=use_ai,
                use_cache=False,
                persist=False,
                show_research=True,
                principal_name=principal_name,
            ),
        )

    def tasks(self, result):
        records = (result.get("structured_records") or {}).get("assignments") or [{}]
        return {item["task"]: item for item in records[0].get("assignments") or []}

    def run_cli(self, args):
        return CliRunner().invoke(
            gang_cli.cli,
            args,
            env={"GANG_HOME": str(self.home), "ANTHROPIC_API_KEY": ""},
            catch_exceptions=False,
        )


# ============================================================ intent routing


class OwnershipRoutingTests(unittest.TestCase):
    def test_what_does_daniel_need_to_do_is_an_ownership_question(self):
        intent = intent_module.infer_intent("what does Daniel need to do?")

        self.assertEqual(intent.policy, intent_module.OWNERSHIP)
        self.assertEqual(intent.subject, "Daniel")
        self.assertTrue(intent.wants_assignments)
        self.assertFalse(intent.wants_identity)

    def test_ownership_phrasings_resolve_the_person(self):
        cases = {
            "what does Daniel need to do?": "Daniel",
            "what do I need to do?": "I",
            "what are Daniel's action items?": "Daniel",
            "what is Frank supposed to do?": "Frank",
            "what does Steven own right now?": "Steven",
            "what is due for Daniel this week?": "Daniel",
            "what are my tasks?": "my",
            "what's assigned to me?": "me",
            "What does Frank Godchaux need to deliver?": "Frank Godchaux",
        }
        for question, subject in cases.items():
            with self.subTest(question=question):
                intent = intent_module.infer_intent(question)
                self.assertEqual(intent.policy, intent_module.OWNERSHIP)
                self.assertEqual(intent.subject, subject)

    def test_neighbouring_questions_keep_their_own_routes(self):
        self.assertEqual(intent_module.infer_intent("who is Daniel?").policy, intent_module.DEFINITION)
        self.assertEqual(intent_module.infer_intent("what does GANG do?").policy, intent_module.DEFINITION)
        # There is no separate involvement policy on this branch; the point is
        # that a history-of-work question is not captured as a task list.
        self.assertEqual(intent_module.infer_intent("what has Daniel worked on?").policy, intent_module.LOOKUP)
        listing = intent_module.infer_intent("show me emails from Daniel")
        self.assertTrue(listing.listing)
        self.assertNotEqual(listing.policy, intent_module.OWNERSHIP)
        self.assertEqual(intent_module.infer_intent("what should I do this week?").policy, intent_module.PLAN)
        self.assertEqual(intent_module.infer_intent("what open action items are there?").policy, intent_module.DECISION)
        self.assertEqual(intent_module.infer_intent("who owns certification?").policy, intent_module.DECISION)

    def test_pronouns_are_not_people(self):
        for question in ("what does it need to do?", "what do we need to do?", "what does This need to do?"):
            with self.subTest(question=question):
                self.assertNotEqual(intent_module.infer_intent(question).policy, intent_module.OWNERSHIP)

    def test_ownership_routes_to_assignments_not_the_canonical_description(self):
        intent = intent_module.infer_intent("what does Daniel need to do?")

        routes = deterministic_module.capability_routes("what does Daniel need to do?", _Plan(), intent)

        self.assertEqual([route["tool"] for route in routes], ["find_assignments"])
        self.assertEqual(routes[0]["arguments"]["person"], "Daniel")


class _Plan:
    text_queries = ["daniel", "need"]
    entity_ids = []
    date_range = None


# ================================================================ extraction


class AssignmentGrammarTests(unittest.TestCase):
    def gather(self, body, name="Daniel", **kwargs):
        row = {"document_id": "doc-1", "title": "Doc", "updated": "2026-09-20", "body": body}
        return [item.task for item in assignments_module.gather([row], assignments_module.person_from(name, **kwargs))]

    def test_the_named_subject_of_an_obligation_is_assigned(self):
        self.assertEqual(
            self.gather("Daniel will confirm the registration source."),
            ["Confirm the registration source"],
        )
        self.assertEqual(self.gather("Daniel to obtain formal 3PL pricing."), ["Obtain formal 3PL pricing"])
        self.assertEqual(
            self.gather("@Daniel Hirunrusme <daniel@gang.example>: Get CE the art file for the PCB."),
            ["Get CE the art file for the PCB"],
        )
        self.assertEqual(
            self.gather("Add this as a Gantt dependency with Daniel as owner."),
            ["Add this as a Gantt dependency"],
        )

    def test_mentions_near_ownership_words_are_not_assignments(self):
        for body in (
            "Daniel noted that GANG-Tech owns the work product.",
            "As the owner of the daniel@gang.example account, you can manage delegates.",
            "We will meet with Daniel to discuss the launch.",
            "Hi Daniel to follow up on our call, here is the deck.",
            "Thanks Daniel, will do.",
            "Attendees: Daniel Hirunrusme, Frank Godchaux. The review moved.",
            "Daniel will be out on Friday.",
            "Daniel I will send over your amended K-1.",
        ):
            with self.subTest(body=body):
                self.assertEqual(self.gather(body), [])

    def test_a_resolved_name_does_not_absorb_a_different_surname(self):
        person = {"aliases": ["Frank"], "resolved": True}
        self.assertEqual(self.gather("Frank Smith will send the invoice.", "Frank Godchaux", **person), [])
        self.assertEqual(
            self.gather("Frank will send the invoice.", "Frank Godchaux", **person),
            ["Send the invoice"],
        )


# ================================================================== answers


class OwnershipAnswerTests(OwnershipTestCase):
    def test_what_does_daniel_need_to_do_returns_a_task_list(self):
        self.seed()

        result = self.ask("what does Daniel need to do?")

        self.assertEqual(result["intent"]["policy"], intent_module.OWNERSHIP)
        self.assertEqual(result["synthesis"]["reason"], deterministic_module.ASSIGNMENTS_REASON)
        self.assertEqual([entry["tool"] for entry in result["research"]["trace"]], ["find_assignments"])
        self.assertFalse(result["insufficient_evidence"])
        self.assertTrue(result["answer"].startswith("Daniel — current action items"))
        self.assertNotIn("couldn't find evidence", result["answer"])
        self.assertIn("- Confirm Shopify build requirements and required OK-RM assets", result["answer"])
        # A task list, not a list of document titles.
        self.assertNotIn("Found ", result["answer"])
        self.assertNotIn("Executive Board Meeting 28 Notes", result["answer"])

    def test_no_authored_description_is_required(self):
        seeded = self.seed()
        self.assertFalse(seeded["daniel"].foundational)
        self.assertFalse(seeded["frank"].foundational)

        daniel = self.ask("what does Daniel need to do?")
        frank = self.ask("what does Frank need to do?")

        for result in (daniel, frank):
            tools = [entry["tool"] for entry in result["research"]["trace"]]
            self.assertNotIn("get_entity", tools)
            self.assertNotIn("entity_profile", tools)
            self.assertTrue(self.tasks(result))

    def test_explicit_assignments_are_returned_with_dates_and_status(self):
        self.seed()

        tasks = self.tasks(self.ask("what does Daniel need to do?"))

        shopify = tasks["Confirm Shopify build requirements and required OK-RM assets"]
        self.assertEqual(shopify["deadline"], "2026-09-04 (OVERDUE)")
        self.assertEqual(shopify["status"], assignments_module.IN_PROGRESS)
        self.assertEqual(shopify["basis"], "owner-field")

        gantt = tasks["Draft integrated Master Gantt Chart through mid-2027"]
        self.assertEqual(gantt["deadline"], "Sep. 18 — Noon")
        self.assertEqual(gantt["basis"], "owner-table")

        shared = tasks["Meet with Creative Engineering and close information requests"]
        self.assertEqual(shared["co_owners"], ["Frank"])

        # Stated twice (minutes and recap); whichever phrasing is kept, the
        # deadline only one of them gives survives the merge.
        [upc] = [item for task, item in tasks.items() if "UPC registration source" in task]
        self.assertEqual(upc["deadline"], "Friday")

    def test_every_task_line_is_cited(self):
        self.seed()

        result = self.ask("what does Daniel need to do?")

        task_lines = [line for line in result["answer"].splitlines() if line.startswith("- ")]
        self.assertTrue(task_lines)
        for line in task_lines:
            with self.subTest(line=line):
                self.assertRegex(line, r"\[\d+\]$")
        for claim in result["claims"]:
            self.assertTrue(claim["citations"])
        cited = {source["document_id"] for source in result["sources"] if source["cited"]}
        self.assertIn(SCHEDULE_ID, cited)
        self.assertIn(MINUTES_ID, cited)

    def test_attendee_mentions_are_not_assignments(self):
        self.seed()

        result = self.ask("what does Dana need to do?")

        # Dana is on the attendee list, the subject of "noted", someone else's
        # meeting partner, and the object of Frank's deliverable. None of it
        # assigns Dana anything.
        self.assertEqual(result["intent"]["policy"], intent_module.OWNERSHIP)
        self.assertEqual(self.tasks(result), {})
        self.assertTrue(result["insufficient_evidence"])
        self.assertEqual(result["claims"], [])
        self.assertIn("no tasks explicitly assigned to Dana", result["answer"])
        self.assertNotIn(NO_EVIDENCE, result["answer"])

    def test_duplicate_actions_collapse_into_one_cited_line(self):
        self.seed()

        result = self.ask("what does Daniel need to do?")
        upc = [task for task in self.tasks(result) if "UPC" in task]

        self.assertEqual(len(upc), 1)
        self.assertEqual(
            set(self.tasks(result)[upc[0]]["document_ids"]), {MINUTES_ID, FOLLOWUP_ID}
        )
        self.assertEqual(result["answer"].count("UPC registration source"), 1)

    def test_completed_and_superseded_work_is_kept_apart_from_current_work(self):
        self.seed()

        result = self.ask("what does Daniel need to do?")
        tasks = self.tasks(result)
        current, _, closed = result["answer"].partition("Completed or superseded")

        self.assertEqual(tasks["Renew the trademark filing"]["status"], assignments_module.DONE)
        self.assertEqual(tasks["Book the Shenzhen factory visit"]["status"], assignments_module.SUPERSEDED)
        # The newest statement of status wins: in progress on 09-08, done on 09-21.
        self.assertEqual(tasks["Order the PCB art proof"]["status"], assignments_module.DONE)
        self.assertEqual(
            set(tasks["Order the PCB art proof"]["document_ids"]), {SCHEDULE_ID, OLD_SCHEDULE_ID}
        )
        for task in ("Renew the trademark filing", "Book the Shenzhen factory visit", "Order the PCB art proof"):
            with self.subTest(task=task):
                self.assertNotIn(task, current)
                self.assertIn(task, closed)
        self.assertIn("Confirm Shopify build requirements", current)

    def test_what_does_frank_need_to_do_works_the_same_way(self):
        self.seed()

        result = self.ask("what does Frank need to do?")
        tasks = self.tasks(result)

        self.assertEqual(result["intent"]["subject"], "Frank")
        for task in (
            "Formally escalate BOM delay to Creative Engineering",
            "Send the prototype photographs to Eliro",
            "Include Dana on future factory-selection calls",
            "Draft the Qi certification checklist",
            "Meet with Creative Engineering and close information requests",
        ):
            with self.subTest(task=task):
                self.assertIn(task, tasks)
        self.assertNotIn("Confirm Shopify build requirements and required OK-RM assets", tasks)
        # Frank resolved through a verified alias, so no literal-name caveat.
        self.assertEqual(result["uncertainty"], "")

    def test_an_unresolved_name_is_matched_literally_and_says_so(self):
        self.seed()

        result = self.ask("what does Daniel need to do?")

        self.assertIn("No canonical person record or verified alias matched", result["uncertainty"])

    def test_first_person_uses_the_principal_identity(self):
        self.seed()

        mine = self.ask("what do I need to do?", principal_name="Daniel")
        named = self.ask("what does Daniel need to do?")

        self.assertEqual(set(self.tasks(mine)), set(self.tasks(named)))
        self.assertTrue(mine["answer"].startswith("Daniel — current action items"))

    def test_first_person_without_a_principal_is_not_guessed(self):
        self.seed()

        result = self.ask("what do I need to do?")

        self.assertTrue(result["insufficient_evidence"])
        self.assertIn("can't tell who", result["answer"])
        self.assertEqual(result["claims"], [])

    def test_due_this_week_scopes_by_deadline_through_the_end_of_the_week(self):
        self.seed()

        # Wednesday 2026-09-02. The Shopify task is due Friday 09-04: after
        # today, but still this week.
        result = self.ask("what is due for Daniel this week?", clock=date(2026, 9, 2))
        tasks = self.tasks(result)

        self.assertEqual(list(tasks), ["Confirm Shopify build requirements and required OK-RM assets"])
        self.assertNotIn("Renew the trademark filing", tasks)
        self.assertNotIn("Order the PCB art proof", tasks)


class NoModelCallTests(OwnershipTestCase):
    def test_no_model_is_called_for_a_deterministic_task_list(self):
        self.seed()

        # use_ai=True on purpose: every provider explodes if reached.
        result = self.ask("what does Daniel need to do?", use_ai=True)

        self.assertEqual(result["provider_calls"], [])
        self.assertEqual(result["synthesis"]["mode"], "deterministic")
        self.assertEqual(result["planner"], "deterministic")


class NeighbouringAnswerTests(OwnershipTestCase):
    def test_who_is_still_a_definition_question(self):
        self.seed()

        result = self.ask("who is Frank?", use_ai=False)

        self.assertEqual(result["intent"]["policy"], intent_module.DEFINITION)
        self.assertNotIn("find_assignments", [entry["tool"] for entry in result["research"]["trace"]])

    def test_show_me_emails_is_still_a_listing(self):
        self.seed()

        result = self.ask("show me emails from Frank", use_ai=False)

        self.assertNotEqual(result["intent"]["policy"], intent_module.OWNERSHIP)
        self.assertEqual(result["synthesis"]["reason"], "listing-question")


# ======================================================== no-evidence output


class NoEvidenceRenderingTests(OwnershipTestCase):
    def test_cli_prints_the_no_evidence_sentence_once(self):
        self.seed()

        output = self.run_cli(["ask", "zyzzyva quuxblatt", "--no-ai"]).output

        self.assertEqual(output.count(NO_EVIDENCE), 1)

    def test_web_client_renders_the_no_evidence_sentence_once(self):
        output = run_node_stage3_check(
            textwrap.dedent(
                f"""
                const mount = document.createElement('div');
                window.GangAskTesting.renderAssistantResult(mount, {{
                  intent: {{mode: 'evidence'}},
                  answer: "I couldn't find evidence in the private corpus to answer that.",
                  claims: [],
                  uncertainty: {NO_EVIDENCE!r},
                  uncertainties: [{NO_EVIDENCE!r}],
                  insufficient_evidence: true,
                  sources: []
                }});
                const text = collectText(mount);
                const count = text.split({NO_EVIDENCE!r}).length - 1;
                assert(count === 1, 'no-evidence sentence rendered ' + count + ' times');
                """
            )
        )
        self.assertEqual(output.strip(), "ok")


class CliOwnershipTests(OwnershipTestCase):
    def test_cli_answers_a_first_person_question_from_the_sole_principal(self):
        self.seed()
        PrincipalDirectory(self.home / "access/principals.yml").save(
            [Principal(principal_id="daniel", display_name="Daniel")]
        )

        output = self.run_cli(["ask", "what do I need to do?", "--no-ai"]).output

        self.assertIn("Daniel — current action items", output)
        self.assertIn("Confirm Shopify build requirements", output)
        self.assertIn("answered deterministically: deterministic-assignments", output)


if __name__ == "__main__":
    unittest.main()
