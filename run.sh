#!/bin/bash
# Mac/Linux用: ./run.sh build | new | import | publish
cd "$(dirname "$0")"
case "$1" in
  new)     python3 ai_new_page.py ;;
  import)  python3 ai_import.py ;;
  publish) git add -A && git commit -m "update site" && git push ;;
  *)       python3 build.py ;;
esac
