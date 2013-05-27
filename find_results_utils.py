"""
Plugin to allow editing find results and propogating to the appropriate files.
"""

import re
import datetime
import sublime
import sublime_plugin

#############################################
# CONSTANTS
#

# Regexs for scanning Find Results buffer.
if sublime.platform() == "windows":
	# Needs more work to account for varying paths.
	STRING_PATH_REGEX = "([a-zA-Z]\:[^:]*):$"
else:
	STRING_PATH_REGEX = "(\/[^:]*):$"

PATH_REGEX = re.compile(STRING_PATH_REGEX)
ML_PATH_REGEX = re.compile(STRING_PATH_REGEX, re.MULTILINE)

ML_FIND_RESULTS_HEADER_REGEX = re.compile("Searching [0-9]+ files for \".*\"", re.MULTILINE)
FIND_RESULTS_HEADER_REGEX = re.compile("Searching [0-9]+ files for \".*\"")
ML_FIND_RESULTS_FOOTER_REGEX = re.compile("1 match in 1 file|[0-9]+ matches in 1 file|[0-9]+ matches across [0-9]+ files", re.MULTILINE)

# Holds original Find Results state.
ORIGINAL_FOUND_DATA = {}
LAST_FOUND_TIME = None

# Used to store state while files are loaded for modification.
PENDING_FILE_CHANGES = {
				   		  "options":{}, 
				   		  "files":{}
				  	   }

# Constants to check state in parse_find_results
LOOKING_FOR_FILE_MODE = 0
PARSING_CHANGES_MODE = 1

#############################################
# PENDING_FILE_CHANGES
#
def add_pending_file(file_name, changes):
	"""
	"""
	PENDING_FILE_CHANGES["files"][file_name] = {"changes":changes}

def reset_pending_file_changes():
	"""
	"""
	global PENDING_FILE_CHANGES
	PENDING_FILE_CHANGES = {
				   			 "options":{}, 
				   			 "files":{}
				  	  	   }

def get_pending_files():
	"""
	"""
	return PENDING_FILE_CHANGES.get("files")

def get_pending_files_length():
	"""
	"""
	return len(PENDING_FILE_CHANGES.get("files"))

def get_pending_options():
	"""
	"""
	return PENDING_FILE_CHANGES.get("options")

def get_pending_file_changes(file_name):
	"""
	"""
	return PENDING_FILE_CHANGES.get("files").get(file_name).get("changes")

def get_pending_file_view(file_name):
	"""
	"""
	return PENDING_FILE_CHANGES.get("files").get(file_name).get("view")	

def add_pending_file_view(file_name, view):
	"""
	"""
	PENDING_FILE_CHANGES["files"][file_name]["view"] = view

def get_command_option(option_name, default=None):
	"""
	"""
	return PENDING_FILE_CHANGES.get("options").get(option_name, default)

def set_command_option(option_name, value):
	"""
	"""
	PENDING_FILE_CHANGES["options"][option_name] = value

#############################################
# ORIGINAL_FOUND_DATA
#
def get_original_found_data():
	"""
	"""
	global ORIGINAL_FOUND_DATA
	return ORIGINAL_FOUND_DATA

def set_original_found_data(data):
	"""
	"""
	global ORIGINAL_FOUND_DATA
	ORIGINAL_FOUND_DATA = data

#############################################
# LOADED_FILES
#
def reset_loaded_files():
	"""
	"""
	global LOADED_FILES
	LOADED_FILES = []

def get_loaded_files():
	"""
	"""
	return LOADED_FILES

def add_loaded_file(file_name):
	"""
	"""
	LOADED_FILES.append(file_name)

def get_loaded_files_length():
	"""
	"""
	return len(LOADED_FILES)

#############################################
# PARSE LAST FOUND RESULTS
#
def find_last_find_results(data):
	"""
	Finds and returns the last find results.
	"""
	matches = [match for match in ML_FIND_RESULTS_HEADER_REGEX.finditer(data)]
	if not matches:
		return None
	
	start_pos = matches[-1].start(0)

	match = ML_FIND_RESULTS_FOOTER_REGEX.search(data, start_pos)
	if match == None:
		return None
	end_pos = match.end(0)

	return data[start_pos:end_pos]

def parse_find_results(data):
	"""
	Data is a single find results block.
	Returns a dictionary {
							"< file_name >":{
											  "< line # >":"< line_data >", 
											  ...
											 }, 
							...,
						  }
	"""
	find_results = data.splitlines()
	if len(find_results) < 2:
		return {}

	match = re.match("^Searching [0-9]+ files for \".*\"", find_results[0])
	if match == None:
		return {}

	mode = LOOKING_FOR_FILE_MODE

	files_to_change = {}
	current_file_name = ""
	current_file_changes = {}

	for current_line in find_results:
		if mode == LOOKING_FOR_FILE_MODE:
			match = re.match(PATH_REGEX, current_line)
			if match != None:
				current_file_name = match.group(1)
				current_file_changes = {}
				mode = PARSING_CHANGES_MODE
		
		elif mode == PARSING_CHANGES_MODE:
			if current_line == "":
				files_to_change[current_file_name] = current_file_changes
				mode = LOOKING_FOR_FILE_MODE
			else:
				match = re.match(" *([0-9]+)(?:(?:\: )|(?:  ))(.*)$", current_line)
				if match != None:
					current_file_changes[str(int(match.group(1)) - 1)] = match.group(2)

	# Finish the last files changes.
	if mode == PARSING_CHANGES_MODE:
		files_to_change[current_file_name] = current_file_changes

	return files_to_change

def get_find_result_data(view):
	"""
	Returns the last find result data parsed.
	"""
	data = view.substr(sublime.Region(0, view.size()))
	find_result_block = find_last_find_results(data)
	if not find_result_block:
		return None
	return parse_find_results(find_result_block)

#############################################
# EXECUTE FILE CHANGES
#
def get_changed_data(old_data, new_data):
	"""
	Compares two parsed data dictionaries and returns a new dictionary
	of changes.
	"""
	changed_data = {}
	for file_name in new_data:
		for line in new_data.get(file_name):
			new_line = new_data.get(file_name).get(line)
			old_line = old_data.get(file_name, {}).get(line)
			if new_line != old_line:
				if file_name not in changed_data:
					changed_data[file_name] = {}
				changed_data[file_name][line] = new_line
	return changed_data

def execute_pending_changes():
	"""
	Executes the file changes for each file found in PENDING_FILE_CHANGES.
	"""
	
	for file_name in get_pending_files():
		changes = get_pending_file_changes(file_name)
		view = get_pending_file_view(file_name)
		execute_file_changes(view, changes)
	
	if not get_command_option("save_and_close", False):
		return
	
	for file_name in get_pending_files():
		view = get_pending_file_view(file_name)
		view.run_command("find_results_replace_changes_save_and_close")

def execute_file_changes(view, changes):
	"""
	Actually applies the changes in Find Results to the open files.
	"""
	line_regions = []
	edit = view.begin_edit()
	for change_line, change_text in changes.iteritems():
		line_start = view.text_point(int(change_line), 0)
		line_region = view.line(line_start)

		if view.substr(line_region) != change_text:
			view.replace(edit, line_region, change_text)
			view.show(line_start)
			line_regions.append(line_region)
	view.end_edit(edit)

	if line_regions:
		view.add_regions("FindResultsReplaceChanges", line_regions, "mark", "bookmark", sublime.HIDDEN)

def extract_find_results_from_cursor(data, cursor):
	"""
	Given a string and a cursor position within that string (in chars),
	extracts the find result block that the cursor resides within.
	"""
	match = None
	start_pos = -1;

	for match in RegExp_ML_FindResultsHeader.finditer(data):
		if match.start(0) < cursor:
			start_pos = match.start(0)
			pass
		else:			
			break

	if start_pos == -1:
		return None;

	cursor = cursor - start_pos

	match = None
	for match in RegExp_ML_FindResultsFooter.finditer(data, start_pos):
		pass
	if match == None:
		return None;

	end_pos = match.end(0)

	return data[start_pos:end_pos], cursor

def get_cursor_last_find_results(data, cursor):
	"""
	Given a string containing one or more find results block,
	finds the filename and line number that corresponds to the 
	line the cursor is on.

	Returns None if it could not find the required info.
	Returns a row-encoded filename string "<filename>:<row>" otherwise.
	"""
	match = None
	start_pos = -1;

	file_name = ""

	for match in RegExp_ML_Path.finditer(data):
		if match.start(0) < cursor:
			start_pos = match.start(0)
			file_name = match.group(1)
			pass
		else:			
			break

	if start_pos == -1:
		return None;

	cursor = cursor - start_pos

	data = data[start_pos:len(data)]

	current_character_count = 0;

	for current_line in data.splitlines():
		current_character_count = current_character_count + len(current_line)
		if current_character_count >= cursor:
			match = re.match( " *([0-9]+)(?:(?:\: )|(?:  ))", current_line);
			if match != None:
				return file_name + ":" + match.group(1)
			else:
				return None

#############################################
# SUBLIME COMMAND CLASSES
#
class FindResultsReplaceChangesSaveAndCloseCommand(sublime_plugin.TextCommand):
	"""
	"""
	def run(self, edit):
		self.view.run_command("save")
		self.view.window().focus_view(self.view)
		self.view.window().run_command("close")

class ApplyFindChangesListener(sublime_plugin.EventListener):
	"""
	Event listeners for scene events.
	"""
	
	setting_last_found_time = False

	def on_load(self, view):
		"""
		Used to apply changes that were deferred due to files being loaded.
		"""
		if not get_pending_files():
			return

		file_name = view.file_name()
		add_pending_file_view(file_name, view)
		add_loaded_file(file_name)

		# If all of our files aren't loaded, continue along.
		if get_loaded_files_length() != get_pending_files_length():
			return
		
		execute_pending_changes()

	def on_modified(self, view):
		"""
		used to listen for modifications which allows us to cache the
		original values to compare for changes.
		"""
		if view.name() != "Find Results" or self.setting_last_found_time:
			return
		
		view_size = view.size()
		line_region = view.line(sublime.Region(view_size-1, view_size))
		line_text = view.substr(line_region)
		
		if not ML_FIND_RESULTS_FOOTER_REGEX.match(line_text):
			return

		global LAST_FOUND_TIME

		if not LAST_FOUND_TIME or LAST_FOUND_TIME not in line_text:
			self.setting_last_found_time = True

			set_original_found_data(get_find_result_data(view))
			edit = view.begin_edit()
			LAST_FOUND_TIME = str(datetime.datetime.now())
			view.replace(edit, line_region, "%s @ %s\n"%(line_text[:-1], LAST_FOUND_TIME))
			view.end_edit(edit)
			
			self.setting_last_found_time = False

class FindResultsReplaceChangesCommand(sublime_plugin.WindowCommand):
	"""
	This command moves changes you have made in the Find Results pane into 
	the corresponding files.

	Edited source files are left open in Sublime with changed lines marked.

	Only called if the Find Results view is active.
	"""

	def run(self, save_and_close=False):
		"""
		Runs when command is invoked.
		"""
		view = self.window.active_view()
		if view == None or view.name() != "Find Results":
			return

		# Reset pending changes to make sure it's empty.  Used to store
		# changed data to be used once the files are opened and loaded.
		reset_loaded_files()
		reset_pending_file_changes()

		set_command_option("save_and_close", save_and_close)

		find_result_data = get_find_result_data(view)
		changed_data = get_changed_data(get_original_found_data(), find_result_data)
		
		if changed_data:
			open_files = dict((view.file_name(), view) for view in self.window.views())
			for current_file_name, changes in changed_data.iteritems():
				if current_file_name in open_files:
					execute_file_changes(open_files.get(current_file_name), changes)
				else:
				 	add_pending_file(current_file_name, changes)

			for file_name in get_pending_files():
				self.window.open_file(file_name)

			set_original_found_data(find_result_data)
		# else:
		# 	view.erase_status("Info:")
		# 	view.set_status("Info:", "No Changes Found.")
