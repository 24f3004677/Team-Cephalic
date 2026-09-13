#!/usr/bin/env bash
set -euo pipefail

# ====== CONFIG ======
# Change this path if you want the output folder somewhere else
OUTPUT_DIR="/mnt/c/Users/Sohamdip/Desktop/Data/Projects/output"
TIMESTAMP="$(date +'%Y-%m-%d_%H-%M-%S')"
OUTPUT_FILE="$OUTPUT_DIR/code_base_${TIMESTAMP}.txt"

# ====== SETUP ======
mkdir -p "$OUTPUT_DIR"

# ====== EXTRACT ======
find . -type f \( -name "*.py" -o -name "*.html" \) -print0 | while IFS= read -r -d '' file; do
    echo "=== $file ===" >> "$OUTPUT_FILE"
    cat "$file" >> "$OUTPUT_FILE"
    echo >> "$OUTPUT_FILE"
done

echo "Snapshot written to $OUTPUT_FILE"
