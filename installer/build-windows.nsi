; ============================================
;  FOL — Windows Installer (NSIS)
;  Builds: FOL-Setup.exe
;  Install to: C:\Program Files\FOL
; ============================================

!include "MUI2.nsh"

; ─── General ────────────────────────────────────────
Name "FOL — AI Assistant"
OutFile "build\FOL-Setup.exe"
InstallDir "$PROGRAMFILES\FOL"
RequestExecutionLevel admin

; ─── Version info ──────────────────────────────────
VIProductVersion "1.3.0.0"
VIAddVersionKey "ProductName" "FOL — AI Assistant"
VIAddVersionKey "FileDescription" "Personal AI Assistant for Windows"
VIAddVersionKey "LegalCopyright" "MIT License"
VIAddVersionKey "FileVersion" "1.3.0"

; ─── Installer pages ───────────────────────────────
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ─── Languages ──────────────────────────────────────
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Russian"

; ─── Installer sections ─────────────────────────────
Section "FOL (Required)" SecMain
    SectionIn RO

    ; Set output path to install directory
    SetOutPath "$INSTDIR"

    ; Install files
    File /r "build\windows-package\*.*"

    ; Create uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Add to Programs and Features
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "DisplayName" "FOL — AI Assistant"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "DisplayVersion" "1.3.0"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "Publisher" "FOL Project"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL" \
        "NoRepair" 1

    ; Create start menu shortcuts
    CreateDirectory "$SMPROGRAMS\FOL"
    CreateShortCut "$SMPROGRAMS\FOL\FOL.lnk" "$INSTDIR\run_all.bat" "" "$INSTDIR\fol-icon.ico"
    CreateShortCut "$SMPROGRAMS\FOL\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

    ; Create desktop shortcut
    CreateShortCut "$DESKTOP\FOL.lnk" "$INSTDIR\run_all.bat" "" "$INSTDIR\fol-icon.ico"
SectionEnd

Section "Python Dependencies" SecDeps
    ; Install Python packages
    DetailPrint "Installing Python packages..."
    nsExec::ExecToLog 'python -m pip install -r "$INSTDIR\requirements-windows.txt" --quiet'
    DetailPrint "Installing system tray support..."
    nsExec::ExecToLog 'python -m pip install pystray Pillow --quiet'
SectionEnd

Section "Configure" SecConfig
    ; Create .env from template if not exists
    IfFileExists "$INSTDIR\.env" skip_env
        CopyFiles "$INSTDIR\.env.template" "$INSTDIR\.env"
    skip_env:

    ; Create start script
    FileOpen $0 "$INSTDIR\Start-FOL.bat" w
    FileWrite $0 '@echo off${\r}${\n}'
    FileWrite $0 'cd /d "$INSTDIR"${\r}${\n}'
    FileWrite $0 'call run_all.bat${\r}${\n}'
    FileClose $0

    DetailPrint "Configuration complete"
SectionEnd

; ─── Uninstaller ────────────────────────────────────
Section "Uninstall"
    ; Remove files
    RMDir /r "$INSTDIR"

    ; Remove shortcuts
    RMDir /r "$SMPROGRAMS\FOL"
    Delete "$DESKTOP\FOL.lnk"

    ; Remove registry keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\FOL"
SectionEnd
