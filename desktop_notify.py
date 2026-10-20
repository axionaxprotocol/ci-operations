"""Windows toast notifications, with no third-party dependency.

The toast is raised through the WinRT ToastNotificationManager, which is present on
Windows 10 and 11. PowerShell is used as the bridge so the application does not need
a WinRT runtime binding, which keeps the packaging dependencies at two packages.

Text that comes from GitHub is XML-escaped before it reaches the toast document, so a
workflow name containing markup cannot break the notification.

The title and body travel in environment variables rather than as command-line
arguments: PowerShell's -Command treats trailing arguments as part of the command
text, so a workflow name would be executed as a command instead of being read.
"""
import logging
import os
import subprocess

LOGGER = logging.getLogger('ci_operations')

APP_ID = 'CI Operations'
POWERSHELL = 'powershell.exe'
TIMEOUT_SECONDS = 20
TITLE_VARIABLE = 'CIOPERATIONS_TOAST_TITLE'
BODY_VARIABLE = 'CIOPERATIONS_TOAST_BODY'

TOAST_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType = WindowsRuntime] | Out-Null
$title = [System.Security.SecurityElement]::Escape($env:CIOPERATIONS_TOAST_TITLE)
$body = [System.Security.SecurityElement]::Escape($env:CIOPERATIONS_TOAST_BODY)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>$title</text><text>$body</text></binding></visual></toast>")
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%s').Show($toast)
""" % APP_ID


def notification_text(job):
    """Return the toast title and body for a failed job."""
    job = job or {}
    workflow = job.get('workflow') or 'A workflow'
    name = job.get('name') or 'a job'
    repo = job.get('repo') or 'a repository'
    title = f'{workflow} failed'
    body = f'{name} failed in {repo}'
    url = job.get('url')
    if url:
        body = f'{body} - {url}'
    return title, body


def notify_failure(job, enabled=True):
    """Raise a Windows toast for a failed job. Returns True when a toast was raised."""
    if not enabled:
        return False
    title, body = notification_text(job)
    environment = dict(os.environ)
    environment[TITLE_VARIABLE] = title
    environment[BODY_VARIABLE] = body
    try:
        completed = subprocess.run(
            [POWERSHELL, '-NoProfile', '-NonInteractive', '-Command', TOAST_SCRIPT],
            timeout=TIMEOUT_SECONDS, check=False, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if completed.returncode != 0:
            LOGGER.info('toast notification failed (%s)', (completed.stderr or '').strip()[:200])
            return False
        return True
    except (OSError, subprocess.SubprocessError) as error:
        LOGGER.info('toast notification could not be raised (%s)', type(error).__name__)
        return False
