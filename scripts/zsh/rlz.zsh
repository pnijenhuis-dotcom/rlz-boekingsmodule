# Werkloop automatisch 14-09 — terminalfunctie `rlz`. Installeren (één regel in ~/.zshrc):
#   source "/Users/mr.x/Claude/Projects/Rlz boekings module/scripts/zsh/rlz.zsh"
#   rlz plan     → scripts/gcp/vgg_blok7_odoo_writes.sh plan (alleen dry-runs, schrijft niets)
#   rlz meting [onderdeel]  → nameting-workflow op GitHub starten (gh workflow run nameting.yml; default alles)
#   rlz status   → git status + de laatste 5 rapporten uit docs/rapporten/INDEX.md
#   rlz inbox    → scripts/cc_inbox.sh nu draaien (zonder op launchd te wachten)
#   rlz          → naar de repo-map
rlz() {
  local repo="/Users/mr.x/Claude/Projects/Rlz boekings module"
  cd "$repo" || return 1
  case "${1:-}" in
    "") ;;
    plan)   shift; "$repo/scripts/gcp/vgg_blok7_odoo_writes.sh" plan "$@" ;;
    meting) shift; gh workflow run nameting.yml -f "onderdeel=${1:-alles}" && echo ">> gestart — volgen: gh run list --workflow nameting.yml --limit 3" ;;
    status) git -C "$repo" status --short --branch; echo; echo "laatste 5 rapporten:"; grep -m5 '^- \[' "$repo/docs/rapporten/INDEX.md" ;;
    inbox)  "$repo/scripts/cc_inbox.sh" ;;
    *)      echo "gebruik: rlz [plan|meting [alles|a|b|c|d|e|reconciliatie]|status|inbox]" >&2; return 2 ;;
  esac
}
