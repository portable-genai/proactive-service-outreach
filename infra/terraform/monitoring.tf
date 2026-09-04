# monitoring.tf: log-based metrics and alert policies for the posture signals.
#
# Principle map (COMPLIANCE.md):
#   P-07 / P-09 (detect, do not merely record): DATA_READ logging (logging_worm.tf) records
#         reads, but recording is not detection. These metrics and policies SURFACE the events
#         that mean the posture slipped, rather than leaving the signal unread in the WORM
#         bucket for the length of the retention window.
#
# Every filter below names a field this deployment actually emits. The managed audit adapter
# writes the AuditEvent as a struct payload, so jsonPayload.decision is "allowed" or
# "escalated" (domain/kernel.py Decision), jsonPayload.severity carries the band, and
# jsonPayload.redacted_summary carries the sentence domain/outreach_service.py built, which
# quotes the eligibility engine's own reason TOKENS (domain/eligibility.py). Those tokens are a
# published vocabulary that the eval oracle and the demo already assert against, so a filter
# that matches one is matching a contract rather than a wording.
#
# Three of the eight are this vertical's own, and they exist because this service sends
# outbound contact and its interesting failure is SILENCE:
#   - consent_unavailable : a contact was refused with consent_unknown, which is what the
#     eligibility engine returns when the marketing-compliance-gate store gave no usable answer at all. Refusing is
#     correct and it is also the shape of a total outage: with the store unreachable this
#     service contacts nobody, forever, while every request still answers 200. Nothing else in
#     the stack would page anyone.
#   - policy_gap_refusals : a refusal caused by frequency_cap_unconfigured or
#     quiet_hours_unconfigured. An unconfigured cap or an unconfigured market DENIES by design,
#     so a policy gap presents as customers not being told things, not as an error. This is the
#     alert that tells the policy owner they have a hole rather than a quiet quarter.
#   - draft_discarded : the validator refused what the model wrote (an invented figure, a
#     banned phrase, personal data, over-length, malformed output). One is a working control;
#     a rate of them is a model or prompt regression, and each one costs a human a review.
#
# There is deliberately NO frequency_cap_exceeded alert. A cap that refuses a fourth message in
# a day is the product working exactly as specified, many times a day, and an alert that fires
# on the intended outcome trains an operator to ignore the channel. The cap is proved by
# `frequency_cap_exactness >= 1.0` in the eval, which is where an arithmetic claim belongs.
#
# There is likewise no guardrail-block metric. The reference stack alerts on one because it
# binds a guardrail port; this service has none (COMPLIANCE rule R1 records that as owed), and
# a metric whose filter can never match is a green light nobody earned. Add it in the same
# commit that binds the guardrail.
#
# Alert policies are always created; var.alert_notification_channels attaches the channels.

locals {
  audit_log_filter = "logName=\"projects/${var.project_id}/logs/${local.audit_log_name}\""

  security_metrics = {
    critical_escalations = {
      description = "Critical-severity escalation recorded in the app audit log (maker-checker, P-06)"
      filter      = "${local.audit_log_filter} AND jsonPayload.decision=\"escalated\" AND jsonPayload.severity=\"critical\""
    }
    consent_unavailable = {
      description = "Contact refused because the consent store gave no usable answer (consent_unknown)"
      filter      = "${local.audit_log_filter} AND jsonPayload.redacted_summary:\"consent_unknown\""
    }
    policy_gap_refusals = {
      description = "Contact refused by an UNCONFIGURED cap or market, which is a policy gap and not a decision"
      filter      = "${local.audit_log_filter} AND (jsonPayload.redacted_summary:\"frequency_cap_unconfigured\" OR jsonPayload.redacted_summary:\"quiet_hours_unconfigured\")"
    }
    draft_discarded = {
      description = "A model draft was discarded by the validator, so a human now has to approve the words"
      filter      = "${local.audit_log_filter} AND jsonPayload.redacted_summary:\"draft discarded\""
    }
    sa_key_creation = {
      description = "Service-account key created (org policy should forbid this)"
      filter      = "protoPayload.methodName=\"google.iam.admin.v1.CreateServiceAccountKey\""
    }
    vpc_sc_denials = {
      description = "VPC Service Controls violation"
      filter      = "protoPayload.metadata.@type=\"type.googleapis.com/google.cloud.audit.VpcServiceControlAuditMetadata\""
    }
    cmek_changes = {
      description = "CMEK key destroy or update operation"
      filter      = "protoPayload.serviceName=\"cloudkms.googleapis.com\" AND (protoPayload.methodName:\"DestroyCryptoKeyVersion\" OR protoPayload.methodName:\"UpdateCryptoKey\")"
    }
    edge_denials = {
      description = "Cloud Armor denied or throttled a request at the serving edge"
      filter      = "resource.type=\"http_load_balancer\" AND jsonPayload.enforcedSecurityPolicy.outcome=\"DENY\""
    }
  }
}

resource "google_logging_metric" "security" {
  for_each = local.security_metrics

  project     = var.project_id
  name        = "${local.metric_prefix}_${each.key}"
  description = each.value.description
  filter      = each.value.filter

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }

  depends_on = [google_project_service.required]
}

resource "google_monitoring_alert_policy" "security" {
  for_each = local.security_metrics

  project      = var.project_id
  display_name = "${var.name_prefix} security: ${each.key}"
  combiner     = "OR"

  conditions {
    display_name = each.value.description

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.security[each.key].name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = var.alert_notification_channels

  documentation {
    content   = "Posture signal '${each.key}' fired for the E5 proactive service outreach service. Investigate the matching entries in Cloud Logging and in the WORM audit bucket (${local.worm_bucket_id})."
    mime_type = "text/markdown"
  }

  depends_on = [google_project_service.required]
}
