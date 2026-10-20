# Completed school files

This folder holds the filled-in onboarding file of each installed school
(`<school>.json`). Every file here except this README is ignored by Git: they
carry teacher passwords and minors' data. **Never commit them**, and never move
them to a tracked path.

To add a school:

1. Copy the blank template: `cp ../plantilla.json <school>.json`
   (`../ejemplo-san-felipe.json` is a complete reference).
2. Fill it in and validate without saving:
   `./seed/onboard.sh --target local --dry-run seed/onboarding/colegios/<school>.json`
3. Load it with the same command without `--dry-run`.

See `docs/school-onboarding.md` for every field and rule.
