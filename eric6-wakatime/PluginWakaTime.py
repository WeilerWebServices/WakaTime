# -*- coding: utf-8 -*-

"""WakaTime plugin for Eric6 and Pymakr."""

from __future__ import unicode_literals

import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import time
import threading
import traceback
from datetime import datetime
from subprocess import PIPE
from zipfile import ZipFile
try:
    import ConfigParser as configparser
except ImportError:
    import configparser
try:
    from urllib2 import urlretrieve
except ImportError:
    from urllib.request import urlretrieve


is_py2 = (sys.version_info[0] == 2)
if is_py2:
    import codecs
    open = codecs.open

from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QObject
try:
    from PyQt5.QtGui import QAction, QInputDialog, QLineEdit
except ImportError:
    from PyQt5.QtWidgets import QAction, QInputDialog, QLineEdit

from E5Gui.E5Application import e5App
from UI.Info import Program, Version


# Start-Of-Header
name = "WakaTime Plugin"
author = "WakaTime <support@wakatime.com>"
autoactivate = True
deactivateable = False
version = "2.0.0"
pluginType = "viewmanager"
pluginTypename = "WakaTime"
className = "WakaTimePlugin"
packageName = None
shortDescription = "Automatic time tracking and metrics about your IDE usage."
longDescription = "Automatic time tracking and metrics about your IDE usage."
pyqtApi = 2
python2Compatible = True
# End-Of-Header

error = ""


if platform.system() == 'Windows':
    RESOURCES_FOLDER = os.path.join(os.getenv('APPDATA'), 'WakaTime')
else:
    RESOURCES_FOLDER = os.path.join(os.path.expanduser('~'), '.wakatime')
if not os.path.exists(RESOURCES_FOLDER):
    os.makedirs(RESOURCES_FOLDER)


HEARTBEAT_FREQUENCY = 2
CLI_LOCATION = os.path.join(RESOURCES_FOLDER, 'wakatime-cli', 'wakatime-cli' + ('.exe' if platform.system() == 'Windows' else ''))
PLUGIN = '{prog}/{progVer} {prog}-wakatime/{pluginVer}'.format(
    prog=Program,
    progVer=Version,
    pluginVer=version,
)
IS_DEBUG_ENABLED = False
S3_HOST = 'https://wakatime-cli.s3-us-west-2.amazonaws.com'


# Log Levels
DEBUG = 'DEBUG'
INFO = 'INFO'
WARNING = 'WARNING'
ERROR = 'ERROR'


def getConfigData():
    return {}


def prepareUninstall():
    """
    Module function to prepare for an uninstallation.
    """
    pass


class WakaTimePlugin(QObject):
    """
    Class implementing the WakaTime plugin.
    """
    def __init__(self, ui):
        """
        Constructor

        @param ui reference to the user interface object (UI.UserInterface)
        """
        super(WakaTimePlugin, self).__init__(ui)
        self._ui = ui

        try:
            e5App().registerPluginObject(pluginTypename, self)
        except KeyError:
            pass    # ignore duplicate registration

    def getProjectHelper(self):
        """
        Public method to get a reference to the project helper object.

        @return reference to the project helper object
        """
        return self.__projectHelperObject

    def initToolbar(self, ui, toolbarManager):
        """
        Public slot to initialize the VCS toolbar.

        @param ui reference to the main window (UserInterface)
        @param toolbarManager reference to a toolbar manager object
            (E5ToolBarManager)
        """
        if self.__projectHelperObject:
            self.__projectHelperObject.initToolbar(ui, toolbarManager)

    def activate(self):
        global IS_DEBUG_ENABLED
        IS_DEBUG_ENABLED = self._getDebug()

        log(DEBUG, 'Initializing WakaTime v{ver}...'.format(ver=version))

        self._setupCli()

        apiKey = self._getApiKey()
        if not apiKey.strip():
            self._promptForApiKey()

        self._setupEventListeners()

        self._addMenu()

        log(DEBUG, 'Finished initializing WakaTime plugin.')
        return None, True

    def deactivate(self):
        """
        Public method to deactivate this plugin.
        """
        self.__object = None

        self.action.setVisible(False)
        self.action.setEnabled(False)

    def _setupCli(self):
        if self._isCliLatest():
            return

        thread = DownloadCLI()
        thread.start()

    def _setupEventListeners(self):
        e5App().getObject('ViewManager').cursorChanged.connect(self._cursorChanged)
        e5App().getObject('ViewManager').editorSaved.connect(self._editorSaved)
        # e5App().getObject('Project').projectOpened.connect(self._projectOpened)

    def _addMenu(self):
        """Adds the WakaTime menu item under the File menu."""
        self.action = QAction(QIcon(), 'WakaTime', self)
        self.action.triggered.connect(self._promptForApiKey)
        fileMenu = e5App().getObject('UserInterface').getMenu('file')
        fileMenu.addAction(self.action)

    def _editorSaved(self, fileName):
        self._handleActivity(fileName, isWrite=True)

    def _cursorChanged(self, editor):
        fileName = editor.getFileName()
        self._handleActivity(fileName)

    def _projectOpened(self):
        log(DEBUG, '_projectOpened')

    def _handleActivity(self, fileName, isWrite=False):
        fileName = os.path.abspath(os.path.realpath(fileName))
        if not hasattr(self, '_lastFile'):
            self._lastFile = None
        if fileName != self._lastFile or self._enoughTimePassed(isWrite):
            if not self._shouldExclude(fileName):
                self._sendHeartbeat(fileName, isWrite)

    def _enoughTimePassed(self, isWrite):
        now = time.time()
        if not hasattr(self, '_lastTime'):
            self._lastTime = 0
        if now - self._lastTime > HEARTBEAT_FREQUENCY * 60:
            return True
        if isWrite and now - self._lastTime > 2:
            return True
        return False

    def _shouldExclude(self, fileName):
        return os.path.basename(fileName) == '0.1'

    def _sendHeartbeat(self, fileName, isWrite):
        if not self._isCliInstalled():
            log(DEBUG, 'Skipping heartbeat because wakatime-cli not found.')
            return

        self._lastFile = fileName
        self._lastTime = time.time()

        args = [CLI_LOCATION, '--entity', fileName, '--plugin', PLUGIN]
        if isWrite:
            args.append('--write')

        log(DEBUG, 'Sending heartbeat:')
        log(DEBUG, ' '.join(args))
        stdout, stderr = Popen(args, stdout=PIPE, stderr=PIPE).communicate()
        if stdout:
            log(DEBUG, 'STDOUT: {}'.format(stdout))
        if stderr:
            log(DEBUG, 'STDERR: {}'.format(stderr))

    def _promptForApiKey(self, *args):
        """Prompt the user to enter their api key."""

        ui = e5App().getObject('UserInterface')
        title = 'WakaTime'
        label = '               Enter your WakaTime API Key:               \n' + \
                '               (https://wakatime.com/settings)            '
        default = self._getApiKey()
        text, ok = QInputDialog.getText(ui, title, label, QLineEdit.Normal, default)
        if ok:
            configs = self._parseConfigFile()
            configs.set('settings', 'api_key', text)
            configFile = self._configFile()
            with open(configFile, 'w', encoding='utf-8') as fh:
                configs.write(fh)

    def _createConfigFile(self):
        """Creates the .wakatime.cfg INI file in $HOME directory, if it does
        not already exist.
        """
        configFile = self._configFile()
        try:
            with open(configFile) as fh:
                pass
        except IOError:
            try:
                with open(configFile, 'w') as fh:
                    fh.write("[settings]\n")
                    fh.write("debug = false\n")
                    fh.write("hidefilenames = false\n")
            except IOError:
                pass

    def _getApiKey(self):
        self._createConfigFile()
        key = ''
        try:
            configs = self._parseConfigFile()
            if configs is not None:
                if configs.has_option('settings', 'api_key'):
                    key = configs.get('settings', 'api_key')
        except:
            pass
        return key

    def _getDebug(self):
        self._createConfigFile()
        try:
            configs = self._parseConfigFile()
            if configs is not None:
                if configs.has_option('settings', 'debug'):
                    return configs.get('settings', 'debug') == 'true'
        except:
            pass
        return False

    def _configFile(self):
        home = os.environ.get('WAKATIME_HOME')
        if home:
            return os.path.join(os.path.expanduser(home), '.wakatime.cfg')

        return os.path.join(os.path.expanduser('~'), '.wakatime.cfg')

    def _parseConfigFile(self):
        """Returns a configparser.SafeConfigParser instance with configs
        read from the config file. Default location of the config file is
        at ~/.wakatime.cfg.
        """

        configFile = self._configFile()

        configs = configparser.SafeConfigParser()
        try:
            with open(configFile, 'r', encoding='utf-8') as fh:
                try:
                    configs.readfp(fh)
                    return configs
                except configparser.Error:
                    log(ERROR, traceback.format_exc())
                    return None
        except IOError:
            log(DEBUG, "Error: Could not read from config file {0}\n".format(configFile))
            return None

    def _isCliInstalled(self):
        return os.path.exists(CLI_LOCATION)

    def _isCliLatest(self):
        if not self._isCliInstalled(self):
            return False

        args = [CLI_LOCATION, '--version']
        stdout, stderr = Popen(args, stdout=PIPE, stderr=PIPE).communicate()
        stdout = (stdout or '') + (stderr or '')
        localVer = self._extractVersion(stdout)
        if not localVer:
            return False

        remoteVer = self._getLatestCliVersion()
        if not remoteVer:
            return True

        return remoteVer == localVer

    def _getLatestCliVersion(self):
        url = getCliVersionUrl()
        try:
            localFile = os.path.join(RESOURCES_FOLDER, 'current_version.txt')
            download(url, localFile)
            ver = None
            with open(localFile) as fh:
                ver = self._extractVersion(fh.read())
            try:
                shutil.rmtree(localFile)
            except:
                pass
            return ver
        except:
            return None

    def _extractVersion(self, text):
        pattern = re.compile(r"([0-9]+\.[0-9]+\.[0-9]+)")
        match = pattern.search(text)
        if match:
            return match.group(1)
        return None

    def prepareUninstall(self):
        """
        Public method to prepare for an uninstallation.
        """
        e5App().unregisterPluginObject(pluginTypename)

    def prepareUnload(self):
        """
        Public method to prepare for an unload.
        """
        if self.__projectHelperObject:
            self.__projectHelperObject.removeToolbar(
                self.__ui, e5App().getObject("ToolbarManager"))
        e5App().unregisterPluginObject(pluginTypename)


class DownloadCLI(threading.Thread):
    """Non-blocking thread for downloading latest wakatime-cli from GitHub.
    """

    def run(self):
        log(INFO, 'Downloading wakatime-cli...')

        try:
            shutil.rmtree(os.path.join(RESOURCES_FOLDER, 'wakatime-cli'))
        except:
            pass

        try:
            url = getCliUrl()
            zip_file = os.path.join(RESOURCES_FOLDER, 'wakatime-cli.zip')
            download(url, zip_file)

            log(INFO, 'Extracting wakatime-cli...')
            with ZipFile(zip_file) as zf:
                zf.extractall(RESOURCES_FOLDER)

            try:
                shutil.rmtree(os.path.join(RESOURCES_FOLDER, 'wakatime-cli.zip'))
            except:
                pass
        except:
            log(DEBUG, traceback.format_exc())

        log(INFO, 'Finished extracting wakatime-cli.')


def download(url, filePath):
    try:
        urlretrieve(url, filePath)
    except IOError:
        ssl._create_default_https_context = ssl._create_unverified_context
        urlretrieve(url, filePath)


def log(lvl, msg, *args, **kwargs):
    if lvl == DEBUG and not IS_DEBUG_ENABLED:
        return
    if len(args) > 0:
        msg = msg.format(*args)
    elif len(kwargs) > 0:
        msg = msg.format(**kwargs)
    date = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
    try:
        print('[WakaTime] [{date}] [{lvl}] {msg}'.format(lvl=lvl, date=date, msg=msg))
    except UnicodeDecodeError:
        print('[WakaTime] [{date}] [{lvl}] {msg}'.format(lvl=lvl, date=date, msg=msg.decode('utf8', 'replace')))


def getCliUrl():
    os = platform.system().lower().replace('darwin', 'mac')
    arch = '64' if sys.maxsize > 2**32 else '32'
    return '{host}/{os}-x86-{arch}/wakatime-cli.zip'.format(
        host=S3_HOST,
        os=os,
        arch=arch,
    )


def getCliVersionUrl():
    os = platform.system().lower().replace('darwin', 'mac')
    arch = '64' if sys.maxsize > 2**32 else '32'
    return '{host}/{os}-x86-{arch}/current_version.txt'.format(
        host=S3_HOST,
        os=os,
        arch=arch,
    )


class Popen(subprocess.Popen):
    """Patched Popen to prevent opening cmd window on Windows platform."""

    def __init__(self, *args, **kwargs):
        is_win = platform.system() == 'Windows'
        if is_win:
            startupinfo = kwargs.get("startupinfo")
            try:
                startupinfo = startupinfo or subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            except AttributeError:
                pass
            kwargs["startupinfo"] = startupinfo
        if "env" not in kwargs:
            env = os.environ.copy()
            env["LANG"] = "en-US" if is_win else "en_US.UTF-8"
            if env.get("LD_LIBRARY_PATH_ORIG"):
                env["LD_LIBRARY_PATH"] = env["LD_LIBRARY_PATH_ORIG"]
            kwargs["env"] = env
        subprocess.Popen.__init__(self, *args, **kwargs)
