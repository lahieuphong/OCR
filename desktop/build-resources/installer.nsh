; VietDoc OCR offline installer (internal proof of concept: INTERNAL / NOT FOR DISTRIBUTION).
; Hooks for electron-builder's assisted NSIS installer (nsis.include in electron-builder.installer.yml):
;   - per-user only: the install-mode page is skipped and the installer never asks for elevation;
;   - a page that lets the user choose a Desktop shortcut (off by default; the Start Menu shortcut is
;     always created by electron-builder); a silent install (/S) creates no Desktop shortcut;
;   - the uninstaller removes that shortcut. Application data (%APPDATA%\VietDoc OCR) is kept.
; Nothing here downloads anything, writes outside the install folder and the user's shortcuts, or runs code.

!ifndef BUILD_UNINSTALLER
  Var VietDocDesktopCheckbox
  Var VietDocDesktopShortcut
!endif

!macro customInit
  StrCpy $VietDocDesktopShortcut "0"
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
  ${If} $VietDocDesktopShortcut == "1"
    CreateShortCut "$DESKTOP\${SHORTCUT_NAME}.lnk" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" "" "$INSTDIR\${APP_EXECUTABLE_FILENAME}" 0 "" "" "${APP_DESCRIPTION}"
    ClearErrors
    WinShell::SetLnkAUMI "$DESKTOP\${SHORTCUT_NAME}.lnk" "${APP_ID}"
  ${EndIf}
!macroend

!macro customUnInstall
  ${If} ${FileExists} "$DESKTOP\${SHORTCUT_NAME}.lnk"
    WinShell::UninstShortcut "$DESKTOP\${SHORTCUT_NAME}.lnk"
    Delete "$DESKTOP\${SHORTCUT_NAME}.lnk"
  ${EndIf}
!macroend
