#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -lt 2 ]]; then
  echo "usage: $0 <region> <parameter-name> [secret-value]" >&2
  exit 1
fi

REGION="$1"
PARAMETER_NAME="$2"

if [[ "$#" -ge 3 ]]; then
  SECRET_VALUE="$3"
else
  read -r -s -p "Secret value: " SECRET_VALUE
  echo
  read -r -s -p "Confirm secret value: " SECRET_CONFIRM
  echo

  if [[ "$SECRET_VALUE" != "$SECRET_CONFIRM" ]]; then
    echo "secret values did not match" >&2
    exit 1
  fi
fi

if [[ -z "$SECRET_VALUE" ]]; then
  echo "secret value cannot be empty" >&2
  exit 1
fi

aws ssm put-parameter \
  --region "$REGION" \
  --name "$PARAMETER_NAME" \
  --type SecureString \
  --overwrite \
  --value "$SECRET_VALUE"
