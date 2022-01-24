"""@package docstring
Main file in the Gitlab-Course-Manager (gcm) package responsible for connecting to Gitlab and manipulating
for the purpose of posting and autograding student coding assignments."""

import gitlab
import pandas as pd
import os, sys, subprocess
import logging
import configparser as cp
import json
import tempfile
import pygit2 as git
import shutil

import config


###### "Private" helper methods that really don't need to be called from outside this package ######

"""Lambda helper to expand the default settings path or the path provided by the argument
@param f Path to the params file or None. If None default of ~/.gcm/settings.ini will be used"""
_get_config_file = lambda f : os.path.expanduser("~/.gcm/settings.ini") if f is  None else os.path.expanduser(f)

def _check_config_section_exists(s, c, f) -> None :
    """Raise an exception if section 's' is not in config 'c' read from file 'f'"""
    if not s in c:
        raise ValueError(f"File {f} must contain a section '[{s}]'")

def _check_config_key_exists(k, s, f) -> None :
    """Raise an exception if section 'k' is not in config section 's' read from file 'f'"""
    if not k in s:
        raise ValueError(f"File {f} must contain an entry '{k}' in section '[{s}]'")

def _get_auth_info(config_file = None) -> dict :
    """Helper function to get the URL and PA token from the settings file. 
    @param settings_file Full path to the config file. This can be updated in a fork
    to use a different format for initialization so long as the dictionary returned has
    the correct key-value pairs."""
    settings = cp.ConfigParser()
    config_file = _get_config_file(config_file)
    settings.read(config_file)
    _check_config_section_exists('setup', settings, config_file)
    setup = settings['setup']
    # Make sure we have the required information! 
    check = lambda x : _check_config_key_exists(x, setup, config_file)
    check('url')
    check('pa_token')
    check('ssh_path')
    check('ssh_type')
    (ssh_type := setup['ssh_type'])
    if ssh_type!= 'id_rsa':
        logging.warning(f"SSH type is '{ssh_type}' but the only tested type is 'id_rsa'")
    logging.debug(f"Got URl as {setup['url']}")

    return {'url' : setup['url'],
            'pa_token' : setup['pa_token'],
            'ssh_path' : setup['ssh_path'],
            'ssh_type' : setup['ssh_type']}



def _get_groups_info(config_file = None) -> dict:
    """Helper function to get the student group ID for the top-level student groups
    @params config_file Full path to the config file. """
    settings = cp.ConfigParser()
    config_file = _get_config_file(config_file)
    settings.read(config_file)
    _check_config_section_exists('groups', settings, config_file)
    group_set = settings['groups']
    check = lambda x : _check_config_key_exists(x, group_set, config_file)
    check('student_group_id')
    check('template_group_id')
    
    return {'student_group_id' : int(group_set['student_group_id']),
            'template_group_id' : int(group_set['template_group_id'])}


def _get_course_info(config_file = None) -> dict :
    """Helper function to get the configuration parameters related to the course
    @params config_file Path to the config file"""
    settings = cp.ConfigParser()
    config_file = _get_config_file(config_file)
    settings.read(config_file)
    if not 'course' in settings:
        raise ValueError(f"File {config_file} must contain a section '[course]'")
    course_set = settings['course']
    if not 'roster' in course_set:
        raise ValueError(f"File {config_file} must contain an entry 'roster' in the '[course]' section")
    roster_f = course_set['roster']
    logging.debug(f"Got course roster {roster_f}")

    return {'roster' : roster_f}



def _get_toplevel_student_group(gl, config_file = None):
    """Helper function to get the top-level student group where each subgroup corresponts to one 
    student in the course
    @param gl The GitLab object which has been authenticated via connect 
    @param config_file Optional path to the configuration file"""
    id = _get_groups_info(config_file)['student_group_id']
    logging.debug(f"Getting GitLab group object for ID {id} (top-level student group)")
    
    return gl.groups.get(id, lazy=True)


def _get_student_group(gl, student, config_file = None):
    student_groups = _get_toplevel_student_group(gl, config_file).subgroups.list(all=True)
    id = None
    for g in student_groups:
        if (g.name == _get_student_groupname(student)):
            id = g.id
            break
    if id is None:
        raise RuntimeError(f"Was unable to find group for student {_get_student_groupname(student)}")

    return gl.groups.get(id)


def _get_template_group(gl, config_file = None):
    """Helper function to get the template group given the config
    @param gl The authenticated GitLab object
    @param config_file Optional path to the config file"""
    id = _get_groups_info(config_file)['template_group_id']
    logging.debug(f"Getting GitLab group object for ID {id} (template group)")

    return gl.groups.get(id, lazy=True)


"""Helper function (which can be updated in, e.g., a fork) to read the roster into a Pandas
DataFrame. I use an Excel file but anything that can be read into a df should work later. 
@params f The file to read"""
_read_course_roster = lambda f : pd.read_excel(f)

"""Helper function (which can be updated in, e.g., a fork) to get the student's first name
from their row in the Pandas DataFrame
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_firstname = lambda s : s['First Name']

"""Helper function (which can be updated in, e.g., a fork) to get the student's last name
from their row in the Pandas DataFrame
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_lastname = lambda s : s['Last Name']

"""Helper function (which can be updated in, e.g., a fork) to get the student group name
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_groupname = lambda s : _get_student_firstname(s) + " " + _get_student_lastname(s)

"""Helper function (which can be updated in, e.g., a fork) to get the student group path
@params s The student's entry in the DataFrame (e.g,. the row of the Excel sheet)"""
_get_student_grouppath = lambda s : f"{_get_student_firstname(s)}-{_get_student_lastname(s)}".replace(' ', '-').lower()


_get_student_username = lambda s : s['Username']

def _get_course_roster(config_file = None) -> pd.DataFrame :
    """Helper function to read the course roster from the configuration file
    @param config_file Optional path to the configuration file"""
    roster_f = _get_course_info(config_file)['roster']
    roster = _read_course_roster(roster_f)

    return roster


def _get_student_user_id(gl, student) -> int :
    user = gl.users.list(search=_get_student_username(student))
    id = None
    for u in user:
        if u.username == _get_student_username(student):
            id = u.id
            break
    if id is None:
        raise ValueError(f"Could not find username for {_get_student_firstname(s)} {_get_student_lastname(s)}")
    return id


###### "Public" package methods ######

def connect(settings_file = None) -> None:
    """Function to establish connection to Gitlab. 
    @param settings_path Optional path to the settings.ini file. Default is ~/.gcm/settings.ini"""
    config_file = os.path.expanduser("~/.gcm/settings.ini") if settings_file is None else settings_file
    logging.debug(f"Got settings path of {config_file}")
    setup = _get_auth_info(config_file)
    logging.debug("Attempting to connect to GitLab ...")
    gl = gitlab.Gitlab(setup['url'], private_token=setup['pa_token'], api_version=4)
    gl.auth()

    return gl


def make_student_groups(gl, settings_file = None, access_level = gitlab.const.MAINTAINER_ACCESS) -> None:
    """Function to create student groups where each student group houses all "projects" which are each student's 
    assignments. Each group named according to the function _get_student_groupname
    @params gl The authenticated GitLab object 
    @params settings_file The path to the confuration file"""
    if access_level < gitlab.const.MAINTAINER_ACCESS:
        logging.warning(f"GitLab access level set to {access_level} which is less than 'maintainer' access. ")
    roster = _get_course_roster(settings_file)
    for _ , student in roster.iterrows():
        groupname = _get_student_groupname(student)
        group_to_create = {
            'name' : groupname,
            'visibility' : 'private',
            'path' : _get_student_grouppath(student),
            'parent_id' : _get_groups_info(settings_file)['student_group_id']
        }
        logging.debug(f"Creating group\n{json.dumps(group_to_create, sort_keys=False, indent=2)}")
        group = gl.groups.create(group_to_create, retry_transient_errors = True)
        member_to_add = {
            'username' : _get_student_username(student),
            'access_level' : access_level,
            'user_id' : _get_student_user_id(gl, student)
        }
        member = group.members.create(member_to_add, retry_transient_errors = True)
        logging.debug(f"Adding member to group\n{json.dumps(member_to_add, sort_keys=False, indent=2)}")



def create_student_assignment(gl, student, student_subgroups, temp_proj_loc, proj_name, settings_file = None) -> int :
    """Function to create a single student assignment from a given template assignment. Returns the 
    GitLab ID of the project"""
    # Get this student's group from the list of subgroups in the top-level group that we get through the argument
    # and not each time this function is called for efficiency (especially with large class sizes)
    (group_name := _get_student_groupname(student))
    logging.debug(f"Creating group for {group_name}")
    student_group = None
    for g in student_subgroups:
        if g.name == group_name:
            student_group = gl.groups.get(g.id)
            logging.debug(f"Found group ID for {group_name} of {student_group.id}")
            break
    if student_group is None:
        raise RuntimeError(f"Unable to find group for student {group_name}")
    # Make a project in the student's group
    proj_to_create = {
        'name' : proj_name,
        'namespace_id' : student_group.id
    }
    proj = gl.projects.create(proj_to_create)
    # Delete the git repository in the downloaded template location, reinit, and upload to a project created inside the student's group
    shutil.rmtree(f"{temp_proj_loc}/.git")
    repo = git.init_repository(temp_proj_loc, origin_url=proj.ssh_url_to_repo)
    repo.remotes.set_url("origin", proj.ssh_url_to_repo)
    (index := repo.index).add_all()
    index.write()
    me = git.Signature("Connor Fuhrman", "connorfuhrman@email.arizona.edu")
    repo.create_commit("refs/head/master", me, me, f"Initial commit for assignment '{proj_name}' for student {group_name}",
                       index.write_tree(), [repo.head.get_object().hex])
    remote = index.remotes["origin"]
    (keypair := git.Keypair("git", os.path.expanduser("~/.ssh/id_rsa.pub"), os.path.expanduser("~/.ssh/id_rsa"), ""))
    (callbacks := git.RemoteCallbacks(credentials = keypair))
    remote.push(['refs/heads/master'], callbacks=callbacks)
    
        
    
    

def post_assignment(gl, temp_proj_path, settings_file = None) -> None :
    """Function to post an assignment given some template project which resides in
    a group for template projects. Each student will get a project created in their group
    which is the template project with a fresh git repository initialized
    @params gl The authenticated GitLab object
    @params temp_proj_path The local path, e.g., 'homework-1-aww-geez-man' of the template project 
    @params settings_file The parameterization file"""
    roster = _get_course_roster(settings_file)
    template_group = _get_template_group(gl, settings_file)
    # Get the project which holds the template
    _p_id = gl.groups.get(template_group.id).projects.list(all=True)
    try:
        _idx = [i.path for i in _p_id].index(temp_proj_path)
    except:
        logging.error(f"Template project {temp_proj_path} cannot be found in group ID {template_group_id} which contains "
                      "projects: {_p_id}")
        raise RuntimeError(f"Unable to find template project {temp_proj_path}. See logs for further detail")
    template_proj = gl.projects.get(_p_id[_idx].id, lazy=False)
    # Open a temporary directory within the context manager so contents are deleted after
    # this script exits
    with tempfile.TemporaryDirectory() as tmpdirname:
        logging.debug(f"Created temporary download directory: {tmpdirname}")
        # Set up the PyGit2 module's download step via the SSH config
        auth_info = _get_auth_info(settings_file)
        ssh_path = config.path(auth_info['ssh_path'])
        (keypair := git.Keypair("git", os.path.expanduser("~/.ssh/id_rsa.pub"), os.path.expanduser("~/.ssh/id_rsa"), ""))
        (callbacks := git.RemoteCallbacks(credentials = keypair))
        (ssh_url := template_proj.ssh_url_to_repo)
        logging.debug(f"Downloading repository from {ssh_url}")
        # Download the template project to the newly created directory
        (temp_proj_loc := config.path(f"{tmpdirname}/template_proj"))
        git.clone_repository(ssh_url, temp_proj_loc, callbacks = callbacks)
        # For each student in the roster create a new git repository with the contents that we just cloned and upload that to
        # a new project as a first commit
        student_subgroups = _get_toplevel_student_group(gl, settings_file).subgroups.list(all=True)
        proj_ids = [create_student_assignment(gl, s, student_subgroups, temp_proj_loc, temp_proj_path, settings_file) for _ , s in roster.iterrows()]
    



##### Function for local testing #####
def _localtest(file = None):
    gl = connect(file)
    make_student_groups(gl, file)
    #post_assignment(gl, 'homework-1-aww-geez-man', file)



if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    _localtest()
