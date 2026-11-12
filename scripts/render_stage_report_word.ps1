param(
    [string]$reportDocx = 'D:\EduMathBench\汇报材料\EduMathBench_阶段工作汇总_2026-10-15.docx',
    [string]$reportDir = 'D:\EduMathBench\data\reports\stage_report_qa_20261015'
)
$ErrorActionPreference = 'Stop'
$reportPdf = Join-Path $reportDir 'word_render.pdf'
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$reportApp = $null
$reportDocument = $null
$ownsEmptyInstance = $false
try {
    $reportApp = New-Object -ComObject Word.Application
    if ($reportApp.Documents.Count -ne 0) {
        throw 'Refusing to modify a Word instance with existing documents.'
    }
    $ownsEmptyInstance = $true
    $reportApp.Visible = $false
    $reportApp.DisplayAlerts = 0
    $reportApp.AutomationSecurity = 3
    $reportDocument = $reportApp.Documents.Open($reportDocx, $false, $true, $false)
    $reportDocument.Repaginate()
    $reportPageCount = $reportDocument.ComputeStatistics(2)
    $reportDocument.ExportAsFixedFormat($reportPdf, 17)
    Write-Output ('Pages: ' + $reportPageCount)
    Write-Output $reportPdf
} finally {
    if ($null -ne $reportDocument) {
        $reportDocument.Close(0)
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($reportDocument)
    }
    if ($null -ne $reportApp) {
        if ($ownsEmptyInstance) { $reportApp.Quit(0) }
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($reportApp)
    }
}
