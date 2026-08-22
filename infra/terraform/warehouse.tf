# warehouse.tf: the client-owned event view, which this stack deliberately does not create.
#
# This file creates no dataset, no table and no view, and that absence is the design rather
# than an omission. The managed EventDetectionPort adapter (adapters/gcp/events.py) reads a
# view the CLIENT owns, and the view is the contract: this service never learns how a payment
# ledger records a decline, only that the view exposes event_id, event_type, subject_id,
# occurred_at, market, locale, detail, source_system and attributes. A dataset created here
# would be a second, empty place for events to not be, and pointing the service at it would be
# this repo deciding what an operational event is.
#
# So the file's whole job is ACCESS, and only the narrowest kind:
#   - roles/bigquery.jobUser is granted at project scope in iam.tf, because a parameterised
#     query has to run a job somewhere and it runs here.
#   - roles/bigquery.dataViewer is granted at DATASET scope, below, and only when
#     var.event_view_dataset names a dataset in this project. A project-wide dataViewer would
#     hand this service every table the bank has, to read one view.
#
# When the view lives in ANOTHER project (the common case, because the ledger does), leave
# var.event_view_dataset empty and grant the `app_service_account` output roles/
# bigquery.dataViewer in that project's own configuration. This stack cannot grant what it
# cannot see, and pretending otherwise with a project-wide role would be the wrong trade.
#
# Principle map (COMPLIANCE.md):
#   P-03 (residency): a view outside var.region is a residency decision this stack cannot make
#         for the client. The org policy (org_policy.tf) constrains what is CREATED here; a
#         pre-existing dataset elsewhere is the adopter's own review, and docs/runbook.md says
#         so.
#   P-09: read-only, dataset-scoped, one grant.

resource "google_bigquery_dataset_iam_member" "app_event_view_reader" {
  count = var.event_view_dataset == "" ? 0 : 1

  project    = var.project_id
  dataset_id = var.event_view_dataset
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.app.email}"

  depends_on = [google_project_service.required]
}
