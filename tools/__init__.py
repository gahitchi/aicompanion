"""Jade's agent tools (filesystem, system, web, calendar, games, journal, …).

This file makes `tools` a *regular* package, not a namespace package. Without it,
Python would merge this directory with any other top-level `tools/` on sys.path —
e.g. the one shipped (badly) by the `ko_speech_tools` distribution in site-packages
— and imports would resolve by path order rather than deterministically.
"""
