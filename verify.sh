#!/bin/bash
export PYTHONPATH=$PYTHONPATH:.

echo "Running black..."
black .

echo "Running mypy on examples..."
mypy examples --python-version 3.14

echo "Running mypy on tests..."
mypy tests --python-version 3.14

echo "Running pytest..."
pytest

echo "Packaging examples..."
./package_examples.sh
