$sites = @(
  @{N='Shanghai RSJ'; U='https://rsj.sh.gov.cn'; F=@('https://rsj.sh.gov.cn/feed.xml','https://rsj.sh.gov.cn/rss.xml')},
  @{N='Shanghai SHEITC'; U='https://sheitc.sh.gov.cn'; F=@('https://sheitc.sh.gov.cn/feed.xml')},
  @{N='Shanghai STCSM'; U='https://stcsm.sh.gov.cn'; F=@('https://stcsm.sh.gov.cn/feed.xml')},
  @{N='Shanghai Gov'; U='https://shanghai.gov.cn'; F=@('https://shanghai.gov.cn/feed.xml','http://www.shanghai.gov.cn/feed.xml')},
  @{N='MOT'; U='https://mot.gov.cn'; F=@('https://mot.gov.cn/feed.xml')},
  @{N='MOHRSS'; U='https://mohrss.gov.cn'; F=@('https://mohrss.gov.cn/feed.xml')},
  @{N='NDRC'; U='https://ndrc.gov.cn'; F=@('https://ndrc.gov.cn/feed.xml')},
  @{N='MIIT'; U='https://miit.gov.cn'; F=@('https://miit.gov.cn/feed.xml')},
  @{N='ChinaTax'; U='https://chinatax.gov.cn'; F=@('https://chinatax.gov.cn/feed.xml')},
  @{N='SHJob'; U='https://shjob.gov.cn'; F=@('https://shjob.gov.cn/feed.xml')},
  @{N='CJob'; U='https://cjob.gov.cn'; F=@('https://cjob.gov.cn/feed.xml')},
  @{N='SCS'; U='https://scs.gov.cn'; F=@('https://scs.gov.cn/feed.xml')},
  @{N='CNIPA'; U='https://cnipa.gov.cn'; F=@('https://cnipa.gov.cn/feed.xml')}
)
foreach($s in $sites) {
  $found = $null
  foreach($f in $s.F) {
    try {
      $r = Invoke-WebRequest -Uri $f -Method Head -TimeoutSec 8 -UseBasicParsing 2>$null
      if($r.StatusCode -eq 200) {
        $ct = $r.ContentType
        if($ct -match 'xml|rss|atom') { $found = $f; break }
      }
    } catch {}
  }
  Write-Host ('{0}|{1}|{2}' -f $s.N, $s.U, $found)
}
