# Omarchy Hotkeys Cheat Sheet

A printable A4 cheat sheet of Omarchy keyboard shortcuts. The sheet has two pages.

**Download:** [omarchy-hotkeys.pdf](omarchy-hotkeys.pdf)

## What is in it

The sheet contains every hotkey table from the official Omarchy manual:

- window and workspace navigation
- system control panels and application launchers
- the clipboard, capture and notifications
- style, toggles and adjustments
- reminders and notices
- Tmux and the Ghostty terminal
- the file manager and Neovim (LazyVim)
- quick completions and emoji mnemonics

## How to use it

Print the PDF at 100% scale. Do not select "fit to page". The sheet uses two A4 pages with two columns on each page.

Omarchy also shows a live reference:

- `Super + K` shows the main bindings
- `Super + Alt + K` shows the Tmux bindings
- `Super + Ctrl + K` shows the Herdr bindings

Your own bindings are in `~/.config/hypr/bindings.lua`. Those bindings replace the bindings on this sheet.

## Building the PDF

```
pip install -r requirements.txt
python generate_cheatsheet.py
```

The script reads <https://omarchy.org/manual/hotkeys/> and writes the PDF. The script holds no shortcut content of its own, so every run produces the current bindings. Run the script again after an Omarchy release to refresh the sheet.

The manual holds more rows than two pages hold at full size. The script therefore reduces the font scale in small steps until the content fits. The script reports the scale that it used. It stops with an error if the content fits no supported scale.

The script docstring describes the flags. `--source` accepts a local HTML file, which gives a repeatable build from a saved copy of the page.

## Caveats

This is an unofficial community sheet. It is not an Omarchy release artifact.

The sheet shows the manual content at the date in the PDF footer. Omarchy changes often. Check the source page first if an entry does not work.

The emoji table keeps the letter mnemonics and the descriptions, and drops the emoji glyphs, because standard PDF fonts contain no emoji. You type the mnemonic, so the sheet keeps the useful part.

## Source, attribution and licence

All shortcut content comes from the Omarchy manual: <https://omarchy.org/manual/hotkeys/>

Omarchy is a trademark of the Omarchy project. This repository has no affiliation with the Omarchy project or with 37signals. Neither organisation endorses it.

### Licence

The layout and the generator script use the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) licence. Reuse them with attribution to this repository.

The shortcut content belongs to the Omarchy project. This repository reproduces that content with attribution to <https://omarchy.org/manual/hotkeys/> and applies no new licence to it.

This repository contains no `LICENSE` file, so GitHub reports the repository as unlicensed. The paragraph above is the licence grant. Open an issue if you need a machine-readable licence file.

## Issues

Report a wrong or missing binding in an issue. Include the hotkey, the function and your Omarchy version. A wrong binding is usually wrong in the manual as well, because the script copies the manual without changes.
