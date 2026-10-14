; ============================================================
;  Inno Setup 6 Script — Planning
;  https://jrsoftware.org/isdl.php
;
;  HOW TO USE:
;    1. Run build.bat first to generate dist\Planning\
;    2. Open this file in Inno Setup Compiler (Ctrl+F9 to build)
;    3. Installer will appear in: installer_output\
; ============================================================

#define AppName      "Planning"
#define AppVersion   "1.0.2"
#define AppPublisher "Delta Dyeing S.A.E."
#define AppExeName   "Planning.exe"
#define SourceDir    "dist\Planning"
#define OutputDir    "installer_output"

[Setup]
; Unique app ID — do not change after first release
AppId={{6F3A2B1C-D4E5-4F60-A7B8-9C0D1E2F3A4B}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}

; Icon shown on the setup .exe itself, and used as the default for
; Add/Remove Programs when the installed app's own exe icon isn't used.
SetupIconFile=icon.ico

; Installation directory
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}

; Output
OutputDir={#OutputDir}
OutputBaseFilename=Planning_Setup_v{#AppVersion}

; Compression
Compression=lzma2/ultra64
SolidCompression=yes
CompressionThreads=auto

; Appearance
WizardStyle=modern
DisableProgramGroupPage=yes

; Privileges — installs per-user (no admin required)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; Architecture
ArchitecturesInstallIn64BitMode=x64compatible

; No uninstaller needed? Set to "no" if you want to keep it simple
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "Create a desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"

[Files]
; Copy the entire PyInstaller output folder into {app}
Source: "{#SourceDir}\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "cache\*,settings\*,logs\*,backups\*,situazione\*,*.db,*.db-*,*.sqlite,*.sqlite-*,*.sqlite3,*.sqlite3-*,*.pkl"

[InstallDelete]
; The app used to be called "Planing" (misspelt).  Same AppId, so installing
; over an old copy upgrades it -- replace the old shortcuts with the new ones.
; (dist\Planning\Planing.exe, the legacy launcher copy made by build.bat, is
; kept on purpose so older versions can still self-update.)
Type: files; Name: "{group}\Planing.lnk"
Type: files; Name: "{commondesktop}\Planing.lnk"
Type: files; Name: "{userdesktop}\Planing.lnk"

[Icons]
; Start Menu
Name: "{group}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    WorkingDir: "{app}"

Name: "{group}\Uninstall {#AppName}"; \
    Filename: "{uninstallexe}"

; Desktop shortcut (optional — user can deselect)
Name: "{commondesktop}\{#AppName}"; \
    Filename: "{app}\{#AppExeName}"; \
    WorkingDir: "{app}"; \
    Tasks: desktopicon

[Run]
; Offer to launch the app after install
Filename: "{app}\{#AppExeName}"; \
    Description: "Launch {#AppName}"; \
    Flags: nowait postinstall skipifsilent; \
    WorkingDir: "{app}"
