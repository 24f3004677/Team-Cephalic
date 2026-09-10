#!/usr/bin/env bash

# Output file
OUTPUT="code_base.txt"

# Clear (or create) the output file
> "$OUTPUT"

# Find all .py and .html files (recursively), process them safely with spaces/newlines
find . -type f \( -name "*.py" -o -name "*.html" \) -print0 | while IFS= read -r -d '' file; do
    # Write a separator with the file name
    echo "=== $file ===" >> "$OUTPUT"
    # Append the file content
    cat "$file" >> "$OUTPUT"
    # Add a trailing newline for readability
    echo >> "$OUTPUT"
    echo >> "$OUTPUT"
    echo >> "$OUTPUT"
done

echo "Done. All contents written to $OUTPUT"
