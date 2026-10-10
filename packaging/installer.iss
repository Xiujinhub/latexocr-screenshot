; Inno Setup 6 脚本：把 dist\LaTeXOCR 打包成安装包 LaTeXOCR-Setup-1.0.0.exe
; 编译（仓库根目录）：
;   "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\installer.iss

#define MyAppName "公式截图识别"
#define MyAppFullName "公式截图识别 (LaTeX-OCR)"
#define MyAppVersion "1.0.0"
#define MyAppExeName "LaTeXOCR.exe"
#define MyDist "..\dist\LaTeXOCR"

[Setup]
AppId={{6F1E4C7A-2B58-4A6E-9E3C-1D8A5B7C9F20}
AppName={#MyAppFullName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppFullName} {#MyAppVersion}
AppPublisher=LaTeX-OCR
DefaultDirName={autopf}\LaTeXOCR
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
; 免管理员：默认装到当前用户的目录，干净电脑上也不用提权
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=LaTeXOCR-Setup-{#MyAppVersion}
SetupIconFile=latexocr.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppFullName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
DisableWelcomePage=no
VersionInfoVersion={#MyAppVersion}
VersionInfoDescription={#MyAppFullName} 安装程序
VersionInfoProductName={#MyAppName}

[Languages]
Name: "chinese"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
; 程序本体 + 所有依赖 + 模型权重
Source: "{#MyDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "extra\使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "extra\检查环境.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\检查环境（自检）"; Filename: "{app}\检查环境.bat"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\使用说明"; Filename: "{app}\使用说明.txt"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 历史记录放在用户目录（%LOCALAPPDATA%\LaTeXOCR），卸载时一并清掉
Type: filesandordirs; Name: "{localappdata}\LaTeXOCR"
