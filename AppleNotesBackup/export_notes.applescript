-- export_notes.applescript
--
-- Dumps every Apple Note to stdout as a control-char-delimited stream so the
-- Python parent can reconstruct one file per note. We go through Notes.app's
-- scripting interface (not the private NoteStore.sqlite blob format) so this
-- keeps working across macOS versions.
--
-- Output format (per note):
--   id US folderPath US name US modificationDate US attachmentCount US body RS
-- where US = ASCII 31 (unit separator), RS = ASCII 30 (record separator).
-- These control chars effectively never appear in note HTML, so the stream is
-- unambiguous even when a note body contains newlines, commas, or tabs.
-- folderPath is the FULL nested path, "/"-separated (e.g. "Archive/FB/FB-UP").
--
-- We walk folders TOP-DOWN and recursively: start at folders whose container is
-- the account (true top level), emit their notes, then recurse into
-- `folders of folder`. Reading a folder's parent via `container` errors (-1728),
-- so we only ever read downward and thread the accumulated path in.
--
-- `body` is the note as HTML (Apple's own rendering) — lossless for text,
-- lists, tables, and checklists. Attachments are reported by count only.

property allRecords : {}
property uSep : (ASCII character 31)
property rSep : (ASCII character 30)

set allRecords to {}

tell application "Notes"
	repeat with acct in accounts
		repeat with f in folders of acct
			if (class of container of f) is account then
				my collectFolder(f, "")
			end if
		end repeat
	end repeat
end tell

set AppleScript's text item delimiters to rSep
set output to (allRecords as string)
set AppleScript's text item delimiters to ""
return output & rSep

-- Emit every note in folder `f` under path `prefix`, then recurse into subfolders.
on collectFolder(f, prefix)
	tell application "Notes"
		set folderName to name of f as string
		if prefix is "" then
			set fullPath to folderName
		else
			set fullPath to prefix & "/" & folderName
		end if
		repeat with n in notes of f
			set noteId to id of n as string
			set noteName to name of n as string
			set noteBody to body of n as string
			set noteModified to (modification date of n) as «class isot» as string
			try
				set attCount to (count of attachments of n) as string
			on error
				set attCount to "0"
			end try
			-- Append to a script property (amortized O(1)); joining once at the end
			-- avoids the O(n^2) blowup of growing an immutable string via `&`.
			set end of my allRecords to (noteId & my uSep & fullPath & my uSep & noteName & my uSep & noteModified & my uSep & attCount & my uSep & noteBody)
		end repeat
		repeat with sub in folders of f
			my collectFolder(sub, fullPath)
		end repeat
	end tell
end collectFolder
