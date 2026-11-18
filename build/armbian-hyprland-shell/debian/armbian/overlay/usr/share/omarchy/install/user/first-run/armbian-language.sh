# Armbian: the shell language follows the system locale that armbian-firstlogin
# set. Upstream sets it in its installer. A language the user chose stays.
language_file=${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/language
[[ -s $language_file ]] && exit 0
locales_json=$OMARCHY_PATH/default/i18n/locales.json
locale=${LANG%%.*}
# The exact locale first (pt_BR is pt-BR), then the language alone (de_AT is de).
code=$(jq -r --arg l "$locale" 'to_entries[] | select((.value.locale | split(".")[0]) == $l) | .key' "$locales_json" | head -n 1)
[[ -n $code ]] || code=$(jq -r --arg c "${locale%%_*}" 'if has($c) then $c else empty end' "$locales_json")
[[ -n $code && $code != en ]] || exit 0
omarchy-language "$code"
