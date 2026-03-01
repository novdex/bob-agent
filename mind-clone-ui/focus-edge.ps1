Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class WinHelper2 {
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
}
"@

$edge = Get-Process msedge -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if ($edge) {
    [WinHelper2]::ShowWindow($edge.MainWindowHandle, 9)
    [WinHelper2]::SetForegroundWindow($edge.MainWindowHandle)
    Write-Host "Edge restored and focused (PID: $($edge.Id))"
} else {
    Write-Host "No Edge window found with main handle"
    # Fallback: open the URL directly
    Start-Process "http://localhost:5173/ui/"
    Write-Host "Opened URL in default browser"
}
