// TABIJI app.js — free, keyless widgets. Fails silently if offline.
(function () {
  var WX_ICON = {0:"☀️",1:"🌤",2:"⛅",3:"☁️",45:"🌫",48:"🌫",51:"🌦",53:"🌦",55:"🌧",
                 61:"🌧",63:"🌧",65:"🌧",71:"🌨",73:"🌨",75:"❄️",80:"🌦",81:"🌧",
                 82:"⛈",95:"⛈",96:"⛈",99:"⛈"};

  // Live weather on destination pages (Open-Meteo: free, no key, CORS OK)
  document.querySelectorAll(".wx").forEach(function (el) {
    var u = "https://api.open-meteo.com/v1/forecast?latitude=" + el.dataset.lat +
            "&longitude=" + el.dataset.lon + "&current_weather=true";
    fetch(u).then(function (r) { return r.json(); }).then(function (j) {
      var c = j.current_weather;
      if (!c) return;
      el.textContent = " · " + el.dataset.label + " " +
        Math.round(c.temperature) + "°C " + (WX_ICON[c.weathercode] || "");
    }).catch(function () {});
  });

  // ¥1,000 in USD / KRW / TWD (open.er-api.com: free, no key)
  var fx = document.querySelector(".fx");
  if (fx) {
    fetch("https://open.er-api.com/v6/latest/JPY").then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j.rates) return;
        var f = function (cur, dp) { return (1000 * j.rates[cur]).toFixed(dp); };
        fx.textContent = "💱 " + fx.dataset.label + " $" + f("USD", 2) +
          " / ₩" + Number(f("KRW", 0)).toLocaleString() +
          " / NT$" + f("TWD", 0);
      }).catch(function () {});
  }
})();
