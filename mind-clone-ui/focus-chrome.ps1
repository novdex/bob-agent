Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class WinHelper {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$chrome = Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($chrome) {
    [WinHelper]::ShowWindow($chrome.MainWindowHandle, 9)  # SW_RESTORE
    [WinHelper]::SetForegroundWindow($chrome.MainWindowHandle)
    Write-Host "Chrome restored and focused (PID: $($chrome.Id))"
} else {
    Write-Host "No Chrome window found"
}
