(function(){
  var el=document.querySelector('.icon-sidebar');
  if(el && localStorage.getItem('tiqRailPinned')==='1') el.classList.add('pinned');
  window.tiqToggleRail=function(){
    var p=el.classList.toggle('pinned');
    localStorage.setItem('tiqRailPinned', p?'1':'0');
    var arrow=document.querySelector('#railPin svg');
    if(arrow) arrow.style.transform = p?'rotate(180deg)':'';
    setTimeout(function(){window.dispatchEvent(new Event('resize'))},250);
  };
  document.getElementById('railPin').addEventListener('click', window.tiqToggleRail);
  document.getElementById('sidebarUserMenu').addEventListener('click', function(){ toggleUserMenu(); });
  document.getElementById('sidebarSignOut').addEventListener('click', function(event){
    event.preventDefault();
    document.getElementById('logoutForm').submit();
  });
  if(el && el.classList.contains('pinned')){
    var arrow=document.querySelector('#railPin svg');
    if(arrow) arrow.style.transform='rotate(180deg)';
  }
})();
