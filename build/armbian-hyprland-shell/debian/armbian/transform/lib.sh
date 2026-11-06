# Helpers for transform rules. Rules run in the upstream tree.

# replace <file> <old> <new> <count>
# Replace a literal string. Fail unless it occurs exactly <count> times.
replace() {
	python3 - "$1" "$2" "$3" "$4" <<- 'EOF'
	import sys
	path, old, new, count = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
	text = open(path, encoding="utf-8").read()
	found = text.count(old)
	if found != count:
	    sys.exit(f"transform: {path}: expected {count} of {old!r}, found {found}")
	open(path, "w", encoding="utf-8").write(text.replace(old, new))
	EOF
}
