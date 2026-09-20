---
id: 01a0bc28-9b26-78da-807e-789734ab0b2a
type: meeting
source_type: meeting
title: Epic 05 Acceptance Meeting
visibility: private
status: active
content_trust: untrusted
created_at: '2026-09-20T00:12:52.902643+00:00'
updated_at: '2026-09-20T00:12:52.902643+00:00'
source_id: meeting_afeabd8689481786aa0304a468e07a02
content_hash: 6d16364880be67abb14797580b8fa3c52f93ce2c3bd977ab17ae650905245012
version: 1
raw_ref: local://meeting/meeting_afeabd8689481786aa0304a468e07a02/v000001/epic05-acceptance-meeting.txt
provenance:
  source_id: meeting_afeabd8689481786aa0304a468e07a02
  source_type: meeting
  raw_ref: local://meeting/meeting_afeabd8689481786aa0304a468e07a02/v000001/epic05-acceptance-meeting.txt
  content_hash: 6d16364880be67abb14797580b8fa3c52f93ce2c3bd977ab17ae650905245012
  version: 1
ingestion_envelope:
  source_type: meeting
  source_id: meeting_afeabd8689481786aa0304a468e07a02
  source_ref: local-source://meeting_afeabd8689481786aa0304a468e07a02
  source_name: epic05-acceptance-meeting.txt
  created_at: '2026-09-20T00:12:52.902643+00:00'
  updated_at: '2026-09-20T00:12:52.902643+00:00'
  participants:
  - Daniel
  - Frank
  attachments: []
  raw_ref: local://meeting/meeting_afeabd8689481786aa0304a468e07a02/v000001/epic05-acceptance-meeting.txt
  content_hash: 6d16364880be67abb14797580b8fa3c52f93ce2c3bd977ab17ae650905245012
  version: 1
  metadata:
    adapter: MeetingTranscriptAdapter
    source_namespace: local-meeting
    source_identity_hash: identity_abd0ac93b058b69591dbab91ef0c32b3
    source_name: epic05-acceptance-meeting.txt
    extension: .txt
summary: 'In the Epic 05 Acceptance Meeting on September 19, 2026, Daniel and Frank
  discussed and decided how Gmail ingestion should work: original messages remain
  immutable source evidence while the canonical knowledge document represents the
  email thread. Frank was assigned to document the Gmail OAuth requirements before
  connector implementation begins. An unresolved question remains about whether attachments
  should be stored locally or moved directly into object storage.'
decisions:
- decision: Gmail messages remain immutable source evidence, while the canonical knowledge
    document represents the email thread.
  evidence:
    document_id: 01a0bc28-9b26-78da-807e-789734ab0b2a
    excerpt: 'Decision: Gmail messages remain immutable source evidence, while the
      canonical knowledge document represents the email thread.'
    source_id: meeting_afeabd8689481786aa0304a468e07a02
action_items:
- task: Document the Gmail OAuth requirements before starting the connector implementation.
  owner: Frank
  evidence:
    document_id: 01a0bc28-9b26-78da-807e-789734ab0b2a
    excerpt: 'Action item: Frank will document the Gmail OAuth requirements.'
    source_id: meeting_afeabd8689481786aa0304a468e07a02
unresolved_questions:
- question: Should attachments live locally or move directly into object storage?
  evidence:
    document_id: 01a0bc28-9b26-78da-807e-789734ab0b2a
    excerpt: One unresolved question is whether attachments should live locally or
      move directly into object storage. We should decide that during the Gmail connector
      work.
    source_id: meeting_afeabd8689481786aa0304a468e07a02
tags:
- gmail
- ingestion
- oauth
- connector
- attachments
- object-storage
- epic-05
- acceptance-meeting
projects: []
companies: []
people:
- Daniel
- Frank
related: []
---

# Epic 05 Acceptance Meeting

Epic 05 Acceptance Meeting
September 19, 2026

Daniel: We need to decide how Gmail ingestion should work.

Frank: I think Gmail should preserve original messages as raw evidence, but canonical knowledge should be organized at the thread level.

Daniel: Agreed. Decision: Gmail messages remain immutable source evidence, while the canonical knowledge document represents the email thread.

Frank: I'll document the Gmail OAuth requirements before we start the connector implementation.

Daniel: Good. Action item: Frank will document the Gmail OAuth requirements.

Daniel: One unresolved question is whether attachments should live locally or move directly into object storage.

Frank: We should decide that during the Gmail connector work.
