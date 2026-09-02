(function () {
  "use strict";

  var CONFIG = window.SAHAYATA_CONFIG || { apiBaseUrl: "http://127.0.0.1:8000", requestTimeoutMs: 20000 };

  var el = {
    form: document.getElementById("searchForm"),
    cityInput: document.getElementById("cityInput"),
    useLocationBtn: document.getElementById("useLocationBtn"),
    searchBtn: document.getElementById("searchBtn"),
    radiusChips: document.getElementById("radiusChips"),
    coordReadout: document.getElementById("coordReadout"),
    connDot: document.getElementById("connDot"),
    connLabel: document.getElementById("connLabel"),

    stateIdle: document.getElementById("stateIdle"),
    stateLoading: document.getElementById("stateLoading"),
    stateError: document.getElementById("stateError"),
    stateEmpty: document.getElementById("stateEmpty"),
    resultsWrap: document.getElementById("resultsWrap"),

    errorHeading: document.getElementById("errorHeading"),
    errorBody: document.getElementById("errorBody"),
    retryBtn: document.getElementById("retryBtn"),

    locationName: document.getElementById("locationName"),
    locationSub: document.getElementById("locationSub"),
    resultsCount: document.getElementById("resultsCount"),
    coverageWarning: document.getElementById("coverageWarning"),
    resultsList: document.getElementById("resultsList"),
  };

  var state = {
    radiusKm: 10,
    coords: null, // { latitude, longitude } when in coordinate mode
    lastQuery: null, // replay for retry button
  };

  var CATEGORY_LABEL = {
    medical: "Medical",
    shelter: "Shelter",
    security: "Security",
    general: "General",
  };

  var FACILITY_LABEL = {
    hospital: "Hospital",
    clinic: "Clinic",
    public_place: "Public facility",
  };

  var ORG_LABEL = {
    government: "Government",
    private: "Private",
    public_sector: "Public sector",
    unclassified: "Unclassified operator",
  };

  function apiUrl(path) {
    var base = (CONFIG.apiBaseUrl || "").replace(/\/+$/, "");
    return base + path;
  }

  function setState(name) {
    ["stateIdle", "stateLoading", "stateError", "stateEmpty"].forEach(function (key) {
      el[key].hidden = key !== name;
    });
    el.resultsWrap.hidden = name !== "results";
  }

  function showResults() {
    ["stateIdle", "stateLoading", "stateError", "stateEmpty"].forEach(function (key) {
      el[key].hidden = true;
    });
    el.resultsWrap.hidden = false;
  }

  function formatDistance(metres) {
    if (metres === null || metres === undefined) {
      return { value: "—", unit: "" };
    }
    if (metres < 1000) {
      return { value: String(Math.round(metres)), unit: "m" };
    }
    return { value: (metres / 1000).toFixed(1), unit: "km" };
  }

  function buildResultRow(resource) {
    var li = document.createElement("li");
    li.className = "result-row";
    li.setAttribute("data-category", resource.category || "general");

    var dist = formatDistance(resource.distance_metres);
    var distEl = document.createElement("div");
    distEl.className = "result-distance";
    distEl.innerHTML = dist.value + (dist.unit ? '<span class="unit"> ' + dist.unit + "</span>" : "");

    var body = document.createElement("div");
    body.className = "result-body";

    var name = document.createElement("p");
    name.className = "result-name";
    name.textContent = resource.name;

    var tags = document.createElement("div");
    tags.className = "result-tags";

    var tagParts = [];
    tagParts.push(CATEGORY_LABEL[resource.category] || resource.category);
    if (resource.facility_type) {
      tagParts.push(FACILITY_LABEL[resource.facility_type] || resource.facility_type);
    }
    if (resource.organisation && resource.organisation.type) {
      var orgText = ORG_LABEL[resource.organisation.type] || resource.organisation.type;
      if (resource.organisation.inferred) orgText += " (inferred)";
      tagParts.push(orgText);
    }
    tagParts.forEach(function (t) {
      var span = document.createElement("span");
      span.textContent = t;
      tags.appendChild(span);
    });

    body.appendChild(name);
    body.appendChild(tags);

    if (resource.source && resource.source.record_url) {
      var link = document.createElement("a");
      link.className = "result-link";
      link.href = resource.source.record_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View source (" + (resource.source.name || "provider") + ")";
      body.appendChild(link);
    }

    li.appendChild(distEl);
    li.appendChild(body);
    return li;
  }

  function renderSuccess(data) {
    el.locationName.textContent = data.location.display_name;
    var subParts = [data.location.state, data.location.country_code === "IN" ? "India" : data.location.country_code]
      .filter(Boolean);
    el.locationSub.textContent = subParts.join(", ");

    var count = data.resources.length;
    el.resultsCount.textContent = count + (count === 1 ? " result" : " results") +
      " within " + Math.round(data.coverage.radius_metres / 1000) + " km";

    if (data.coverage.is_partial && data.coverage.warnings && data.coverage.warnings.length) {
      el.coverageWarning.hidden = false;
      el.coverageWarning.textContent = data.coverage.warnings.join(" ");
    } else {
      el.coverageWarning.hidden = true;
      el.coverageWarning.textContent = "";
    }

    el.resultsList.innerHTML = "";

    if (count === 0) {
      setState("stateEmpty");
      return;
    }

    data.resources.forEach(function (resource) {
      el.resultsList.appendChild(buildResultRow(resource));
    });

    showResults();
  }

  function renderError(errBody, opts) {
    opts = opts || {};
    var err = (errBody && errBody.error) || {
      message: "Couldn't reach the server. Check your connection and try again.",
      retryable: true,
    };

    el.errorHeading.textContent = errorHeadingFor(err.code);
    el.errorBody.textContent = err.message;
    el.retryBtn.hidden = !err.retryable;
    setState("stateError");
  }

  function errorHeadingFor(code) {
    switch (code) {
      case "LOCATION_NOT_FOUND":
        return "City not found";
      case "LOCATION_OUTSIDE_SERVICE_AREA":
        return "Outside the supported area";
      case "RATE_LIMITED":
        return "Too many searches";
      case "UPSTREAM_TIMEOUT":
      case "UPSTREAM_FAILURE":
        return "Data providers are unavailable";
      case "INVALID_REQUEST":
        return "Check your search";
      default:
        return "Couldn't complete the search";
    }
  }

  function runSearch(query) {
    state.lastQuery = query;
    setState("stateLoading");

    var url = apiUrl("/api/v1/resources/nearby?" + query.toString());
    var controller = new AbortController();
    var timeoutId = setTimeout(function () {
      controller.abort();
    }, CONFIG.requestTimeoutMs || 20000);

    fetch(url, { method: "GET", headers: { Accept: "application/json" }, signal: controller.signal })
      .then(function (resp) {
        clearTimeout(timeoutId);
        return resp.json().then(function (body) {
          if (!resp.ok) {
            throw { isApiError: true, body: body };
          }
          return body;
        });
      })
      .then(function (data) {
        renderSuccess(data);
      })
      .catch(function (err) {
        clearTimeout(timeoutId);
        if (err && err.isApiError) {
          renderError(err.body);
        } else if (err && err.name === "AbortError") {
          renderError({ error: { message: "The search took too long and was cancelled. Please try again.", retryable: true } });
        } else {
          renderError(null);
        }
      });
  }

  function searchByCity(city) {
    var query = new URLSearchParams();
    query.set("city", city);
    query.set("radius_km", String(state.radiusKm));
    runSearch(query);
  }

  function searchByCoords(latitude, longitude) {
    var query = new URLSearchParams();
    query.set("latitude", String(latitude));
    query.set("longitude", String(longitude));
    query.set("radius_km", String(state.radiusKm));
    runSearch(query);
  }

  // ---- Event wiring ----

  el.form.addEventListener("submit", function (e) {
    e.preventDefault();
    var city = el.cityInput.value.trim();
    if (city.length < 2) {
      el.errorHeading.textContent = "Check your search";
      el.errorBody.textContent = "Enter at least 2 characters of a city name.";
      el.retryBtn.hidden = true;
      setState("stateError");
      return;
    }
    state.coords = null;
    el.coordReadout.hidden = true;
    searchByCity(city);
  });

  el.useLocationBtn.addEventListener("click", function () {
    if (!navigator.geolocation) {
      el.errorHeading.textContent = "Location isn't available";
      el.errorBody.textContent = "This browser doesn't support sharing your location. Try entering a city instead.";
      el.retryBtn.hidden = true;
      setState("stateError");
      return;
    }
    el.useLocationBtn.disabled = true;
    el.useLocationBtn.textContent = "Locating…";

    navigator.geolocation.getCurrentPosition(
      function (pos) {
        el.useLocationBtn.disabled = false;
        el.useLocationBtn.textContent = "Use my location";
        var lat = pos.coords.latitude;
        var lon = pos.coords.longitude;
        state.coords = { latitude: lat, longitude: lon };
        el.cityInput.value = "";
        el.coordReadout.hidden = false;
        el.coordReadout.textContent = "Searching near " + lat.toFixed(4) + ", " + lon.toFixed(4);
        searchByCoords(lat, lon);
      },
      function () {
        el.useLocationBtn.disabled = false;
        el.useLocationBtn.textContent = "Use my location";
        el.errorHeading.textContent = "Couldn't get your location";
        el.errorBody.textContent = "Location access was blocked or unavailable. Try entering a city instead.";
        el.retryBtn.hidden = true;
        setState("stateError");
      },
      { timeout: 10000 }
    );
  });

  el.radiusChips.addEventListener("click", function (e) {
    var btn = e.target.closest(".chip");
    if (!btn) return;
    Array.prototype.forEach.call(el.radiusChips.querySelectorAll(".chip"), function (c) {
      c.classList.remove("is-selected");
    });
    btn.classList.add("is-selected");
    state.radiusKm = parseInt(btn.getAttribute("data-radius"), 10);

    // Re-run the last search at the new radius, if any.
    if (state.coords) {
      searchByCoords(state.coords.latitude, state.coords.longitude);
    } else if (el.cityInput.value.trim().length >= 2) {
      searchByCity(el.cityInput.value.trim());
    }
  });

  el.retryBtn.addEventListener("click", function () {
    if (!state.lastQuery) return;
    runSearch(state.lastQuery);
  });

  // ---- Health check on load ----

  function checkHealth() {
    var controller = new AbortController();
    var timeoutId = setTimeout(function () { controller.abort(); }, 6000);
    fetch(apiUrl("/api/v1/health"), { signal: controller.signal })
      .then(function (resp) {
        clearTimeout(timeoutId);
        if (resp.ok) {
          el.connDot.className = "dot is-ok";
          el.connLabel.textContent = "Connected";
        } else {
          throw new Error("unhealthy");
        }
      })
      .catch(function () {
        clearTimeout(timeoutId);
        el.connDot.className = "dot is-bad";
        el.connLabel.textContent = "Backend unreachable";
      });
  }

  checkHealth();
})();
