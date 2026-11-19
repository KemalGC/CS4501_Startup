#!/usr/bin/env bash
# Reproducible local packaging only. This script makes a ZIP; it creates no AWS
# infrastructure, does not run terraform apply, and does not push artifacts.
set -euo pipefail

infra_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "${infra_dir}/../.." && pwd)"
build_dir="${infra_dir}/dist/lambda-package"
zip_file="${infra_dir}/dist/strokesense-api-lambda.zip"

mkdir -p "${build_dir}"
mkdir -p "${build_dir}/aws_app"
python3 -m pip install --disable-pip-version-check \
  -r "${project_dir}/strokesense/aws_app/requirements.txt" \
  -t "${build_dir}"
cp -R "${project_dir}/strokesense/aws_app/." "${build_dir}/aws_app/"

(
  cd "${build_dir}"
  zip -q -FS -r "${zip_file}" . -x '*/__pycache__/*' '*/test_*.py'
)

printf 'Built local Lambda ZIP: %s\n' "${zip_file}"
