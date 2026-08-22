# iam.tf: the least-privilege serving identity.
#
# Principle map (COMPLIANCE.md):
#   P-09 (defence in depth, least privilege): one serving identity that holds only the roles
#         the request pipeline needs (read the event view, phrase a body, deliver on the chat
#         channel, write the audio object, write audit and traces, read its own secrets). No
#         shared kitchen-sink account and no primitive roles.
#   P-03 (residency): the identity is project-scoped and every service it reaches is regional.
#   P-13 / R8: asking the Mkt6 consent store and routing an escalation to the Hrz7 console are
#         outbound HTTPS calls carrying service credentials from Secret Manager, not GCP IAM
#         roles, so nothing is granted for either here.
#
# Two access decisions are NOT expressed as a project role, and both are deliberate:
#   - Cloud Text-to-Speech defines no per-caller IAM role for synthesis. Enabling the API in
#     this project (apis.tf) is the access control, so inventing a role here would be
#     inventing a control.
#   - Reading the event view is granted at DATASET scope, not project scope, and only when
#     var.event_view_dataset names a dataset in this project (warehouse.tf). A project-wide
#     bigquery.dataViewer would hand this service every table the bank has.
#
# There is deliberately ONE service account. The reference stack carries a second identity for
# its Agent Runtime; this repo's agent surface is a set of plain tool callables that run inside
# the same process as the API (nothing in agent/ needs a runtime to import), so a second
# identity would have nothing to attach to and would only widen what is provisioned. Add one in
# the same commit that deploys the agent somewhere else, never before.

resource "google_service_account" "app" {
  account_id   = local.app_sa_id
  display_name = "E5 Proactive Service Outreach (serving / API)"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

locals {
  # Every role below is traceable to a bound adapter. aiplatform.user covers the drafting
  # model, which rephrases a body that has already been decided and produces no number.
  app_roles = [
    "roles/aiplatform.user",              # drafting.py
    "roles/dialogflow.client",            # delivery.py (detect_intent, not agent design)
    "roles/bigquery.jobUser",             # events.py (run the query job in this project)
    "roles/logging.logWriter",            # audit.py (write only: it cannot read the WORM trail)
    "roles/cloudtrace.agent",             # tracer.py
    "roles/secretmanager.secretAccessor", # the inbound and the two outbound credential pairs
  ]
}

resource "google_project_iam_member" "app" {
  for_each = toset(local.app_roles)
  project  = var.project_id
  role     = each.value
  member   = "serviceAccount:${google_service_account.app.email}"
}

# The app uses the CMEK for the envelope operations it performs directly.
resource "google_kms_crypto_key_iam_member" "app" {
  crypto_key_id = google_kms_crypto_key.outreach.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.app.email}"
}
