# Encounter release reference

The current merged encounter interface and private engineering status are
maintained in [CURRENT_STATE.md](CURRENT_STATE.md),
[ENCOUNTER_PREPROCESSING.md](ENCOUNTER_PREPROCESSING.md) and
[the release follow-up](../NEXT_STEPS.md). Those records supersede the earlier
unverified-receipt checkpoint formerly recorded here.

`validate-encounters` requires a fresh external report destination. Existing
successful or failed reports retain their exact bytes when a rerun is rejected;
use a new report path and work directory for each validation attempt.

The separate return integration is documented in
[RETURN_ACCEPTANCE.md](RETURN_ACCEPTANCE.md). Acceptance of the original
readmissions revision does not transfer to the integrated package identity.
Historical investigation details remain in the accepted branch's Git history;
private receipts and operator paths remain external.
