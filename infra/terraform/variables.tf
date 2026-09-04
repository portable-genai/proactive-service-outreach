# variables.tf: the only knobs. Everything else is a concrete, prefix-derived value.
#
# Principle map (COMPLIANCE.md):
#   P-03 (residency): `region` is SELECTED AT DEPLOY TIME and validated against
#         var.allowed_regions, so an unvetted region fails at `terraform plan` rather than
#         deciding about a person, or contacting them, out of jurisdiction. The default is
#         asia-southeast1.
#   P-07 (auditability and retention): `retention_days` is a variable because the WORM bucket
#         lock is irreversible, so the retention window has to be a deliberate decision.
#   P-06 / R8 (maker-checker): `human_review_url` is required when the serving edge is
#         enabled, because the managed review router refuses to swallow an escalation with no
#         console configured. A deploy that would ship R8 unwired fails at plan time.
#   P-13 (consented contact): `consent_store_url` is required for the same reason and is this
#         vertical's own version of it. The managed consent adapter has no local fallback and
#         no cached answer, so an unnamed store refuses every contact. That refusal is correct
#         behaviour and a terrible deployment, so the plan refuses first.
#
# Two deploy paths are supported:
#   - QUICK EVALUATION (project-scoped, no org-level roles): project_id plus
#     enable_vpc_sc = false, enable_org_policies = false, worm_locked = false. Everything
#     stays deletable. NOT a compliant production posture.
#   - FULL SOVEREIGN (the default): org-policy guardrails, a dry-run VPC-SC perimeter, and a
#     locked WORM bucket.

variable "project_id" {
  description = "Target GCP project id (required). Single-tenant, in-region."
  type        = string
}

variable "name_prefix" {
  description = <<-EOT
    Prefix for every named resource this stack creates (key ring, buckets, service account,
    metrics, perimeter, Cloud Run service). Two reasons to change it: two instances can then
    coexist in one project, and a destroy plus redeploy does not collide with the
    indestructible KMS key ring the previous stack left behind (key rings can never be
    deleted; a fresh prefix gives a fresh ring).
  EOT
  type        = string
  default     = "outreach"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,18}$", var.name_prefix))
    error_message = "name_prefix must match ^[a-z][a-z0-9-]{2,18}$ (lowercase letter first, then lowercase letters, digits or hyphens, 3 to 19 characters)."
  }
}

variable "allowed_regions" {
  description = <<-EOT
    Residency allowlist: the regions this service may be deployed to. The region is chosen at
    deploy time (var.region) and validated against this list so an operator fails fast (P-03).
    Extend it only after confirming that the whole managed stack (Vertex AI, Text-to-Speech,
    Dialogflow CX, BigQuery, Cloud KMS, Cloud Logging, Cloud Storage, Cloud Run) and the
    residency obligation for the subject data a contact decision turns on are both satisfied in
    that region. This list is the same allowlist the application validates its configured region
    against at settings load.
  EOT
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Defaults to asia-southeast1, the region this
    service pins its data residency to. Validated against var.allowed_regions so an unapproved
    region fails at `terraform plan` rather than moving operational events, consent decisions,
    synthesised audio and the audit trail out of jurisdiction (P-03).
  EOT
  type        = string
  default     = "asia-southeast1"

  validation {
    # Cross-variable validation (Terraform >= 1.9): fails at plan time, which is setup time.
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (the residency allowlist). Add it there first if that region is approved for this workload (P-03)."
  }
}

variable "additional_resource_locations" {
  description = <<-EOT
    Extra values appended to the gcp.resourceLocations allowlist, beyond the selected region's
    own location group. The residency-critical data plane (Cloud Run, KMS, Cloud Logging, Cloud
    Storage, BigQuery, Vertex AI, Text-to-Speech) is entirely regional and needs nothing here.
    The serving edge, however, is built from location-less global objects (the IP address, URL
    map, target proxy, certificate and forwarding rule); an organisation whose policy evaluation
    covers those must list the value its policy expects for them here rather than widening the
    regional allowlist. Empty is the strict default.
  EOT
  type        = list(string)
  default     = []
}

variable "retention_days" {
  description = "WORM audit-log retention in days. Default 180 (six months). The lock is irreversible."
  type        = number
  default     = 180

  validation {
    condition     = var.retention_days >= 180
    error_message = "Compliance retention must be at least 180 days (six months) (P-07)."
  }
}

variable "existing_locked_retention_days" {
  description = "Existing locked bucket retention in days, or 0 for a new stack. A plan may never request a lower value than a bucket already locked at."
  type        = number
  default     = 0

  validation {
    condition     = var.existing_locked_retention_days == 0 || var.existing_locked_retention_days >= 180
    error_message = "existing_locked_retention_days must be 0 for a new stack, or at least 180."
  }

  validation {
    condition     = var.existing_locked_retention_days == 0 || var.retention_days >= var.existing_locked_retention_days
    error_message = "retention_days cannot be lower than the existing locked retention. An existing stack must preserve or increase its locked value."
  }
}

variable "worm_locked" {
  description = <<-EOT
    Lock the WORM audit bucket (P-07, rule R2).
    #########################################################################
    # WARNING: LOCKING IS IRREVERSIBLE. With true, the bucket and its       #
    # retention window can NEVER be reduced or deleted until every entry    #
    # ages out (180 days by default), not even with project-owner rights.   #
    #########################################################################
    true (the default) is REQUIRED for a compliant production deploy: the audit trail is
    Write-Once-Read-Many only when locked, and in this vertical the record of why a person was
    NOT contacted is the one an investigation asks for. Set false ONLY for an evaluation or
    demo stack that must stay deletable; that posture is NOT compliant.
  EOT
  type        = bool
  default     = true
}

variable "enable_org_policies" {
  description = <<-EOT
    Create the project-level Org Policy guardrails (resourceLocations residency pin, no
    service-account key creation, uniform bucket-level access). Requires the caller to hold
    roles/orgpolicy.policyAdmin on the project. Set false for a quick project-scoped
    evaluation deploy without that role; the per-resource region pins still apply, but the
    defence-in-depth layer is skipped, which is NOT compliant for production.
  EOT
  type        = bool
  default     = true
}

variable "allowed_policy_member_domains" {
  description = <<-EOT
    Customer or directory ids (for example "C0xxxxxxx") permitted by the domain-restricted
    sharing org policy (constraints/iam.allowedPolicyMemberDomains). An empty list disables
    that policy. Only applied when enable_org_policies = true.
  EOT
  type        = list(string)
  default     = []
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the organisation.
    Required when enable_vpc_sc = true; the service perimeter is created under it. Create one
    per organisation with:
      gcloud access-context-manager policies create \
        --organization=ORG_ID --title="residency-policy"
  EOT
  type        = string
  default     = ""

  validation {
    condition     = !var.enable_vpc_sc || length(var.access_policy_id) > 0
    error_message = "enable_vpc_sc = true requires access_policy_id. Supply the organisation's Access Context Manager policy id, or set enable_vpc_sc = false for a project-scoped quick deploy."
  }
}

variable "enable_vpc_sc" {
  description = "Create the VPC Service Controls perimeter around the AI and data APIs (P-01, P-03)."
  type        = bool
  default     = true
}

variable "vpc_sc_enforce" {
  description = <<-EOT
    Enforce the VPC-SC perimeter (true) or run it in DRY-RUN / audit mode (false, the
    default). Apply with false first, watch the dry-run violation logs (the monitoring.tf
    alert surfaces them), add the operator and CI identities to var.operator_members, then
    flip to true. Never enforce blind on a path nobody has watched in dry run.
  EOT
  type        = bool
  default     = false
}

variable "operator_members" {
  description = <<-EOT
    Identities (for example "user:you@example.com",
    "serviceAccount:ci@PROJECT.iam.gserviceaccount.com") allowed to reach the
    perimeter-restricted APIs from outside the perimeter, through an Access Context Manager
    access level. An empty list creates no access level.
  EOT
  type        = list(string)
  default     = []
}

variable "alert_notification_channels" {
  description = <<-EOT
    Cloud Monitoring notification channel ids for the security and posture alert policies
    (critical escalations, consent unavailable, policy-gap refusals, discarded drafts,
    service-account key creation, VPC-SC denials, CMEK changes, edge denials). An empty list
    still creates the metrics and policies, with nowhere to notify.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition = !var.production_edge_enabled || (
      length(var.alert_notification_channels) > 0 &&
      alltrue([
        for channel in var.alert_notification_channels :
        can(regex("^projects/[a-z][a-z0-9-]{4,28}[a-z0-9]/notificationChannels/[0-9]+$", channel))
      ])
    )
    error_message = "production_edge_enabled requires at least one valid Cloud Monitoring notification channel: an alert nobody receives is not an alert."
  }
}

variable "event_view_dataset" {
  description = <<-EOT
    BigQuery dataset id, IN THIS PROJECT, holding the client-owned event view the managed
    detection adapter reads (var.event_view). Naming it grants the serving identity
    roles/bigquery.dataViewer on that dataset and nothing wider. Empty (the default) creates no
    grant, which is correct when the view lives in another project: grant it there, to the
    `app_service_account` output, in that project's own configuration. This stack never creates
    the dataset or the view; see warehouse.tf.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.event_view_dataset == "" || can(regex("^[A-Za-z0-9_]{1,1024}$", var.event_view_dataset))
    error_message = "event_view_dataset must be a bare BigQuery dataset id (letters, digits and underscores), not a fully-qualified name."
  }
}

# --------------------------------------------------------------------------- #
# Runtime wiring for the serving edge. Each of these becomes an environment
# variable on the Cloud Run service, so the deployed posture is described here
# rather than assembled by hand at the console.
# --------------------------------------------------------------------------- #

variable "human_review_url" {
  description = <<-EOT
    The human-review-console the managed review router submits escalations to
    (HUMAN_REVIEW_URL). Rule R8 says an escalation is ROUTED and never merely flagged, and
    the managed router refuses rather than swallowing one when this is empty, so the serving
    edge requires it: a deploy that would ship R8 unwired fails here instead of at the first
    fraud hold. HTTPS is required, because the payload carries a redacted outreach result and
    the words a reviewer is being asked to approve.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.human_review_url == "" || can(regex("^https://", var.human_review_url))
    error_message = "human_review_url must be an https:// URL."
  }

  validation {
    condition     = !var.production_edge_enabled || can(regex("^https://", var.human_review_url))
    error_message = "production_edge_enabled requires human_review_url (rule R8): the managed review router refuses to run with no console configured."
  }
}

variable "consent_store_url" {
  description = <<-EOT
    The marketing-compliance-gate consent and preference store this service ASKS on every contact
    (MKT_CONSENT_STORE_URL). Required when the serving edge is enabled, and required for the
    same reason as human_review_url: the managed consent adapter has no local fallback and no
    cached answer, because a second copy of anybody's consent would be a second answer to a
    legal question about a person. With no store named, every contact is refused with
    consent_unknown. That is the correct refusal and a useless deployment, so it is refused at
    plan time instead. HTTPS is required: the query carries a tenant, a subject and a purpose.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.consent_store_url == "" || can(regex("^https://", var.consent_store_url))
    error_message = "consent_store_url must be an https:// URL."
  }

  validation {
    condition     = !var.production_edge_enabled || can(regex("^https://", var.consent_store_url))
    error_message = "production_edge_enabled requires consent_store_url (P-13): with no consent authority named, this service refuses every contact and can do nothing else."
  }
}

variable "event_view" {
  description = <<-EOT
    The fully-qualified, client-owned warehouse view the managed detection adapter reads
    operational events from (OUTREACH_EVENT_VIEW), "project.dataset.view". The view is the
    contract, so this service never learns how a ledger records a decline; this stack therefore
    does not create it (warehouse.tf). Empty leaves the variable unset, and the adapter then
    refuses to detect rather than inventing a source.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.event_view == "" || can(regex("^[A-Za-z0-9_-]+\\.[A-Za-z0-9_]+\\.[A-Za-z0-9_]+$", var.event_view))
    error_message = "event_view must be a fully-qualified project.dataset.view name."
  }
}

variable "drafting_model" {
  description = <<-EOT
    The managed model the drafter phrases a notification with (OUTREACH_DRAFTING_MODEL). Empty
    leaves the variable unset, which the service treats as a discarded draft: the deterministic
    template body goes to a human and nothing is delivered. That is a deliberate, documented
    degradation, so this is not required. Never set it to an empty string on the service.
  EOT
  type        = string
  default     = ""
}

variable "chat_agent" {
  description = <<-EOT
    The Dialogflow CX agent a chat notification is delivered through (OUTREACH_CHAT_AGENT),
    "projects/<P>/locations/<L>/agents/<A>". The agent's conversational design is the client's,
    so this stack does not create it; it enables the API and grants the serving identity
    roles/dialogflow.client. Empty leaves the variable unset and the delivery adapter refuses,
    which holds the notification rather than sending it somewhere nobody chose.
  EOT
  type        = string
  default     = ""
}

variable "speech_voice" {
  description = <<-EOT
    The managed Text-to-Speech voice a voice notification is synthesised with
    (OUTREACH_SPEECH_VOICE), for example "en-SG-Standard-A". The destination bucket is NOT a
    variable: this stack creates it and sets OUTREACH_SPEECH_OUTPUT_URI itself, so synthesised
    audio cannot be written to a location the residency review never saw. Empty leaves the
    voice unset and the speech adapter refuses, which reports an undelivered notification
    rather than a delivered one.
  EOT
  type        = string
  default     = ""
}

variable "service_tenant" {
  description = <<-EOT
    Tenant partition asserted on outbound reviews when the verified principal carries none
    (OUTREACH_TENANT). Empty leaves the variable unset.
  EOT
  type        = string
  default     = ""
}

variable "quality_service_url" {
  description = <<-EOT
    The model-quality-gate AI-quality service that owns the promotion verdict (OUTREACH_QUALITY_URL). Empty
    leaves the variable unset, so the application takes its documented default. Never set it to
    an empty string on the service: the eval adapter treats SET-AND-EMPTY as naming no
    promotion authority at all, and refuses.
  EOT
  type        = string
  default     = ""
}

variable "otlp_endpoint" {
  description = <<-EOT
    OpenTelemetry collector endpoint (OTEL_EXPORTER_OTLP_ENDPOINT, rule R2). Set it to the
    agent-observability collector to send spans there; leave it empty and the tracer exports straight to Cloud
    Trace. Empty means the variable is not set on the service at all.
  EOT
  type        = string
  default     = ""
}

variable "iap_audience" {
  description = <<-EOT
    The IAP-protected resource the managed identity adapter verifies every assertion against
    (OUTREACH_IAP_AUDIENCE): "/projects/<PROJECT_NUMBER>/global/backendServices/<BACKEND_ID>".

    This is deliberately a variable and not a reference to the backend service created here,
    because the backend service is built FROM the Cloud Run service and would form a cycle.
    The first apply therefore leaves it empty, and the application fails closed exactly as
    documented: it starts, stays health-checkable, and refuses every end-user request with a
    503 naming this variable. Read the `iap_audience` output after that apply, set this
    variable to it, and apply again.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.iap_audience == "" || can(regex("^/projects/[0-9]+/global/backendServices/[0-9]+$", var.iap_audience))
    error_message = "iap_audience must be empty or of the form /projects/<PROJECT_NUMBER>/global/backendServices/<BACKEND_SERVICE_ID>."
  }
}

variable "additional_secret_env" {
  description = <<-EOT
    Environment variable name to an immutable existing Secret Manager secret version, mounted
    on the API service. This is how the inbound service credential (OUTREACH_S2S_TOKEN), the
    outbound human-review-console pair (HUMAN_REVIEW_S2S_TOKEN, HUMAN_REVIEW_S2S_SIGNING_KEY) and the outbound marketing-compliance-gate consent
    pair (CONSENT_S2S_TOKEN, CONSENT_S2S_SIGNING_KEY) reach the process: no secret value is
    ever written into this configuration. Three trust relationships, five variables, and the
    three pairs are deliberately distinct. Names this stack sets itself are reserved, so a
    secret cannot silently shadow the residency, identity, consent or routing wiring.
  EOT
  type = map(object({
    secret_id = string
    version   = string
  }))
  default = {}

  validation {
    condition = alltrue([
      for name, secret in var.additional_secret_env :
      can(regex("^[A-Z][A-Z0-9_]{1,127}$", name)) &&
      length(secret.secret_id) > 0 &&
      can(regex("^[1-9][0-9]*$", secret.version)) &&
      !contains([
        "OUTREACH_PROFILE",
        "OUTREACH_SETTINGS",
        "OUTREACH_IAP_AUDIENCE",
        "OUTREACH_EVENT_VIEW",
        "OUTREACH_DRAFTING_MODEL",
        "OUTREACH_CHAT_AGENT",
        "OUTREACH_SPEECH_VOICE",
        "OUTREACH_SPEECH_OUTPUT_URI",
        "OUTREACH_TENANT",
        "OUTREACH_QUALITY_URL",
        "GOOGLE_CLOUD_PROJECT",
        "GCP_REGION",
        "HUMAN_REVIEW_URL",
        "MKT_CONSENT_STORE_URL",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "PORT",
      ], name)
    ])
    error_message = "additional_secret_env requires uppercase non-reserved names, non-empty secret ids and numeric versions (never \"latest\": a moving version is a payload nobody reviewed)."
  }
}

# --------------------------------------------------------------------------- #
# The serving edge itself.
# --------------------------------------------------------------------------- #

variable "production_edge_enabled" {
  description = "Provision the Cloud Run service and its external load-balancer edge. Requires an immutable image and a domain."
  type        = bool
  default     = false
}

variable "api_image" {
  description = "Immutable API image reference including its @sha256 digest."
  type        = string
  default     = ""

  validation {
    condition     = !var.production_edge_enabled || can(regex("@sha256:[0-9a-f]{64}$", var.api_image))
    error_message = "production_edge_enabled requires api_image pinned by @sha256 digest: a tag can be re-pushed, so a tag pin lets what serves change with no diff."
  }
}

variable "service_domain" {
  description = "Dedicated DNS name for the production service origin."
  type        = string
  default     = ""

  validation {
    condition     = !var.production_edge_enabled || can(regex("^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])$", var.service_domain))
    error_message = "production_edge_enabled requires a valid lowercase service_domain."
  }
}

variable "dns_managed_zone" {
  description = "Optional existing Cloud DNS managed zone in which to create service_domain."
  type        = string
  default     = ""
}

variable "edge_iap_enabled" {
  description = <<-EOT
    Put Identity-Aware Proxy in front of the backend service. TRUE is the shipped posture: the
    only identity adapter this service declares VERIFIED is the IAP one, which checks the
    assertion's signature against IAP's own key set, its audience against
    OUTREACH_IAP_AUDIENCE, its expiry and its issuer. With IAP off, no end user can be
    authenticated at all and every end-user route answers 401, so false is only meaningful for
    a service-to-service-only installation that fronts its own identity somewhere else.
  EOT
  type        = bool
  default     = true
}

variable "iap_members" {
  description = <<-EOT
    Principals granted roles/iap.httpsResourceAccessor on the backend service, for example
    "group:service-ops@example.com". Empty grants nobody, which is the correct default: IAP
    with no members denies everyone rather than admitting anyone.
  EOT
  type        = list(string)
  default     = []
}

variable "iap_oauth2_client_id" {
  description = "OAuth 2.0 client id for IAP. Leave empty to use the Google-managed client."
  type        = string
  default     = ""
}

variable "iap_oauth2_client_secret" {
  description = "OAuth 2.0 client secret for IAP. Leave empty to use the Google-managed client."
  type        = string
  default     = ""
  sensitive   = true
}

variable "edge_min_instances" {
  description = "Minimum instances for the API service."
  type        = number
  default     = 1

  validation {
    condition     = var.edge_min_instances >= 0
    error_message = "edge_min_instances must be zero or greater."
  }
}

variable "edge_max_instances" {
  description = "Maximum instances for the API service."
  type        = number
  default     = 10

  validation {
    condition     = var.edge_max_instances >= var.edge_min_instances
    error_message = "edge_max_instances must be greater than or equal to edge_min_instances."
  }
}

variable "edge_per_source_rate_limit_per_minute" {
  description = "Cloud Armor request ceiling per source IP per minute before HTTP 429."
  type        = number
  default     = 120

  validation {
    condition     = var.edge_per_source_rate_limit_per_minute >= 10 && var.edge_per_source_rate_limit_per_minute <= 10000
    error_message = "edge_per_source_rate_limit_per_minute must be from 10 to 10000."
  }
}
