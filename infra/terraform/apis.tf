# apis.tf: enable exactly the managed services this stack depends on.
#
# Principle map (COMPLIANCE.md):
#   P-01 (managed-first, minimal surface): only the services the pinned stack actually uses
#         are enabled. Every entry below is here because a bound gcp adapter calls it; nothing
#         is speculative.
#   P-03 (residency): enabling these is the prerequisite for the regional, CMEK-protected
#         resources the sibling files create.
#
# Two bound adapters need NO API here, and that is worth naming rather than leaving to a
# reader's inference. adapters/gcp/consent.py (the Mkt6 consent and preference store) and
# adapters/gcp/review_router.py (the Hrz7 console, rule R8) are pure stdlib urllib over
# consent-preference-kit and review-kit. They call sibling SERVICES over HTTPS, not Google
# APIs, so they are a network-egress and Secret Manager concern and nothing is enabled for
# them. In particular, depending on consent-preference-kit implies no GCP resource at all.
#
# disable_on_destroy = false, so destroying this stack does not yank platform APIs out from
# under other workloads in a shared project.

locals {
  required_services = [
    # Called by a bound adapter (src/proactive_outreach/adapters/gcp/).
    "aiplatform.googleapis.com",   # drafting.py (a model phrases; it decides nothing)
    "texttospeech.googleapis.com", # speech.py (the voice channel)
    "dialogflow.googleapis.com",   # delivery.py (the CX conversation channel)
    "bigquery.googleapis.com",     # events.py (the client-owned event view)
    "logging.googleapis.com",      # audit.py (the WORM audit sink, rule R2)
    "cloudtrace.googleapis.com",   # tracer.py (spans, structural attributes only)
    "monitoring.googleapis.com",   # log-based metrics and the alert policies
    "run.googleapis.com",          # the serving edge
    "secretmanager.googleapis.com",
    "storage.googleapis.com",  # the bucket synthesised audio is written to
    "cloudkms.googleapis.com", # the regional CMEK key ring
    "iap.googleapis.com",      # the identity edge the one VERIFIED adapter checks against

    # Supporting services the above require.
    "accesscontextmanager.googleapis.com", # the VPC-SC perimeter (P-03)
    "compute.googleapis.com",              # the external load balancer and Cloud Armor
    "iam.googleapis.com",                  # least-privilege service accounts
    "orgpolicy.googleapis.com",            # the residency and key-hygiene constraints (P-03)
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
