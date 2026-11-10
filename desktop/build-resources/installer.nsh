; VietDoc OCR offline installer (internal proof of concept: INTERNAL / NOT FOR DISTRIBUTION).
; Hooks for electron-builder's assisted NSIS installer (nsis.include in electron-builder.installer.yml):
;   - per-user only: the install-mode page is skipped and the installer never asks for elevation;
;   - a page that lets the user choose a Desktop shortcut (off by default; the Start Menu shortcut is
;     always created by electron-builder); a silent install (/S) creates no Desktop shortcut;
;   - the uninstaller removes that shortcut. Application data (%APPDATA%\VietDoc OCR) is kept;
;   - the installer copy electron-builder leaves for an auto-updater is deleted (the app has none).
; Nothing here downloads anything, writes outside the install folder and the user's shortcuts, or runs code.

!ifndef BUILD_UNINSTALLER
  Var VietDocDesktopCheckbox
  Var VietDocDesktopShortcut
!endif

!macro customInit
  StrCpy $VietDocDesktopShortcut "0"
  ; Upgrade: a Desktop shortcut the user already has is kept (preselected, and recreated by a silent upgrade).
  ${If} ${FileExists} "$DESKTOP\${SHORTCUT_NAME}.lnk"
    StrCpy $VietDocDesktopShortcut "1"
  ${EndIf}
!macroend

!macro customInstallMode
  StrCpy $isForceCurrentInstall "1"
!macroend

!macro customPageAfterChangeDir
  Page custom VietDocShortcutPage VietDocShortcutLeave

  Function VietDocShortcutPage
    !insertmacro MUI_HEADER_TEXT "Lối tắt" "Chọn nơi đặt lối tắt mở VietDoc OCR."
    nsDialogs::Create 1018
    Pop $0
    ${NSD_CreateLabel} 0 0 100% 24u "Lối tắt trong Start Menu luôn được tạo."
    Pop $0
    ${NSD_CreateCheckbox} 0 30u 100% 12u "Tạo lối tắt trên Desktop"
    Pop $VietDocDesktopCheckbox
    ${If} $VietDocDesktopShortcut == "1"
      ${NSD_Check} $VietDocDesktopCheckbox
    ${EndIf}
    nsDialogs::Show
  FunctionEnd

  Function VietDocShortcutLeave
    ${NSD_GetState} $VietDocDesktopCheckbox $0
    ${If} $0 == ${BST_CHECKED}
      StrCpy $VietDocDesktopShortcut "1"
    ${Else}
      StrCpy $VietDocDesktopShortcut "0"
    ${EndIf}
  FunctionEnd
!macroend

!macro customInstall
  ; electron-builder keeps a copy of the installer in %LOCALAPPDATA%\<package>-updater\installer.exe for its
  ; auto-updater. VietDoc OCR has no auto-update, so that copy (as large as the installer) is removed again; its
  ; folder goes only if it is then empty.
  !ifdef APP_INSTALLER_STORE_FILE
    Push $0
    Delete "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    ${StdUtils.GetParentPath} $0 "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    RMDir "$0"
    Pop $0
  !endif
  ${If} $VietDocDesktopShortcut == "1"
    CreateShortCut "$DESKTOP\${SHORTCUT_NAME}.lnk" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" 0 "" "" "${APP_DESCRIPTION}"
    ClearErrors
    WinShell::SetLnkAUMI "$DESKTOP\${SHORTCUT_NAME}.lnk" "${APP_ID}"
  ${EndIf}
!macroend

!macro customUnInstall
  ; An upgrade runs the old version's uninstaller with --updated: the shortcut stays for the new version.
  ${ifNot} ${isUpdated}
    ${If} ${FileExists} "$DESKTOP\${SHORTCUT_NAME}.lnk"
      WinShell::UninstShortcut "$DESKTOP\${SHORTCUT_NAME}.lnk"
      Delete "$DESKTOP\${SHORTCUT_NAME}.lnk"
    ${EndIf}
  ${endIf}
!macroend
