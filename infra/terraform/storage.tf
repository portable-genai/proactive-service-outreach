# storage.tf: the in-region bucket the synthesised voice notification is written to.
#
# The managed TextToSpeechPort adapter (adapters/gcp/speech.py) never lets audio bytes into the
# domain: it synthesises, writes the object, and returns an AudioRef. Residency and retention
# are therefore properties of a bucket an operator provisioned, and this is that bucket:
# regional, CMEK-encrypted, uniform access, public access prevented, and not force-destroyable.
# The adapter refuses to synthesise at all when no destination is configured, which is why this
# stack sets OUTREACH_SPEECH_OUTPUT_URI from the bucket it created rather than accepting one as
# a variable: an operator who could name the destination could name an out-of-region one.
#
# Principle map (COMPLIANCE.md):
#   P-03 (residency): location is var.region. A synthesised notification is a recording of what
#         a named customer was told about their own account, and it never leaves the region.
#   P-09: CMEK, with the Cloud Storage service-agent binding in kms.tf. Uniform bucket-level
#         access removes per-object ACLs entirely (org_policy.tf enforces that project-wide).
#   P-04: the body that was synthesised was already validated and already redacted. Nothing in
#         this bucket is read back by a model, and nothing here is read by this service at all.
#
# Retention and deletion of the audio itself are the adopter's schedule to set, so no lifecycle
# rule is imposed here. The audit trail of what was DECIDED and DELIVERED is separate, and that
# one is locked (logging_worm.tf).

resource "google_storage_bucket" "speech" {
  name                        = local.speech_bucket_name
  project                     = var.project_id
  location                    = var.region # in-country audio (P-03)
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  encryption {
    default_kms_key_name = google_kms_crypto_key.outreach.id # CMEK (P-09)
  }

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.storage,
  ]
}

# The serving identity CREATES objects and can neither read them back nor overwrite one.
# objectCreator, not objectAdmin: every synthesis writes a fresh request-id-keyed object, so an
# overwrite would mean replacing the recording of what a customer was told with a different
# one, after the fact, using the same credential that sent it.
resource "google_storage_bucket_iam_member" "app_speech_writer" {
  bucket = google_storage_bucket.speech.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.app.email}"
}
