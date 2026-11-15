#!/usr/bin/bash
# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4 
#

set -e

SCRIPT_DIR=$(dirname "$(realpath "$0")")

PWD=`pwd`

export PS1="(brwap)> "

exec bwrap \
    --ro-bind / / \
    --dev /dev \
    --proc /proc \
    --tmpfs /tmp \
    --bind /run/user/`id -u` /run/user/`id -u` \
    --bind ${PWD} ${PWD} \
    --bind ${HOME}/.python3_history ${HOME}/.python3_history \
    rlwrap python3 ../main.py
    #bash --noprofile --norc

