      (function(){
        var b = document.getElementById('licenseBanner');
        if (!b) return;
        var key = 'licenseBannerDismissed:' + b.dataset.expiry;
        if (sessionStorage.getItem(key) === '1') return;
        b.style.display = 'flex';
        window.dismissLicenseBanner = function(){
          sessionStorage.setItem(key, '1');
          b.style.display = 'none';
        };
        document.getElementById('dismissLicenseBannerBtn').addEventListener('click', window.dismissLicenseBanner);
      })();
