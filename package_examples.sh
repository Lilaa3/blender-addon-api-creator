#!/bin/bash
set -e

DIST_DIR="dist"

# Clean up previous builds
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR"

echo "Packaging examples..."

for addon_path in examples/*/; do
    addon_path=${addon_path%/} # Remove trailing slash
    addon_name=$(basename "$addon_path") # Get just the folder name

    echo "Processing $addon_name..."

    # Create a staging directory to organize the files before zipping
    STAGING_DIR="$DIST_DIR/staging"
    mkdir -p "$STAGING_DIR/$addon_name"

    # Copy files from the source to the staging directory.
    # -L: dereference symbolic links
    cp -rL "$addon_path/"* "$STAGING_DIR/$addon_name/"
    # Remove __pycache__ if it was copied
    find "$STAGING_DIR/$addon_name" -name "__pycache__" -type d -exec rm -rf {} +

    # Create the zip file from the staging directory
    python3 -c "import shutil; shutil.make_archive('$DIST_DIR/$addon_name', 'zip', '$STAGING_DIR', '$addon_name')"

    echo "  -> Created $DIST_DIR/$addon_name.zip"
done

# Clean up staging directory
rm -rf "$DIST_DIR/staging"

echo "Done! Zip files are in $DIST_DIR/"
