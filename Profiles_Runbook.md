# CMS Tooling Profiles Runbook (offline)

Overview
- This runbook documents how to switch destinations using profile files (no environment variables).
- Profiles live at ~/.config/cms-tooling/cms_profiles.json and can be used by Telnet and FTP paths.

Prerequisites
- Local Python 3.12+ environment
- The cms-tooling code checked out in this repo
- A profiles file at the standard location

Creating a profile
- Add entries to cms_profiles.json:
  - A minimal example:
    {
      "default": "default",
      "profiles": [
        { "name": "default", "host": "host1", "port": 23, "ftp_host": "ftp-host1", "ftp_port": 2121 },
        { "name": "lab", "host": "host2", "port": 22, "ftp_host": "ftp-host2", "ftp_port": 2122 }
      ]
    }

Using a profile with Telnet
- Telnet connection via CLI:
  - cms-tooling: cms_telnet_driver.py probe --profile default
- You can use --profile lab for subsequent commands.

Using a profile with FTP
- FTP transfer via CLI:
  - cms-tooling: cms_ftpput.py --profile lab PUT M173NEW.DIRECT C0 M50NEW.DIRECT
- For GETs, replace PUT with GET and provide appropriate remote/local IDs.

Notes
- Profiles do not contain credentials. Maintain credentials separately in the existing secure store.
- If you want to switch destinations in a script, set the profile name when constructing the CmsSession or pass --profile on CLI invocations.
