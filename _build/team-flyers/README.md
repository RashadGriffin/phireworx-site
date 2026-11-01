# Gallery access flyers

Script behind the `phireworx-team-gallery-flyers` skill. Not served on the live
site (`/_build/*` returns 404).

- `make_flyers.py` builds a team's pre-shoot and post-shoot flyers (square post,
  phone-screen version, paste-ready message) and the pre-shoot 4-up print sheet.
- Fonts and the Phireworx logos come from `assets/fonts/` and `assets/images/`.
- Team logos live in `../team-logos/` with `index.json` (one entry per school).

Run: `python3 make_flyers.py team.json out` (see the docstring for team.json).
