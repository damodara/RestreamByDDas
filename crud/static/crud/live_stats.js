(function () {
	var POLL_INTERVAL_MS = 5000;

	function setGauge(gaugeEl, percent, level, text) {
		if (!gaugeEl) return;
		gaugeEl.classList.remove("ok", "warn", "danger", "unknown");
		gaugeEl.classList.add(level);
		gaugeEl.style.setProperty("--pct", level === "unknown" ? 0 : percent);
		var textEl = gaugeEl.querySelector(".gauge-text");
		if (textEl) textEl.textContent = text;
	}

	function updatePercentMetric(root, key, percent, level) {
		var gauge = root.querySelector('[data-gauge="' + key + '"]');
		var value = root.querySelector('[data-value="' + key + '"]');
		if (percent === null || percent === undefined) {
			setGauge(gauge, 0, "unknown", "н/д");
			if (value) value.textContent = "н/д";
			return;
		}
		setGauge(gauge, percent, level, percent + "%");
		if (value) value.textContent = percent + "%";
	}

	function pollServerLoad() {
		var root = document.querySelector("[data-server-load-url]");
		if (!root) return;
		var url = root.dataset.serverLoadUrl;

		function tick() {
			fetch(url, { headers: { Accept: "application/json" } })
				.then(function (r) {
					return r.ok ? r.json() : null;
				})
				.then(function (data) {
					if (!data) return;

					updatePercentMetric(root, "load1", data.load1_percent, data.load1_level);
					var loadValue = root.querySelector('[data-value="load"]');
					if (loadValue) {
						loadValue.textContent =
							data.load1.toFixed(2) +
							" / " +
							data.load5.toFixed(2) +
							" / " +
							data.load15.toFixed(2);
					}

					updatePercentMetric(root, "mem", data.mem_used_percent, data.mem_level);
					updatePercentMetric(root, "disk", data.disk_used_percent, data.disk_level);
				})
				.catch(function () {
					// Пропускаем тик молча — временная сетевая ошибка не должна
					// ломать уже отрисованную страницу, следующий тик попробует снова.
				});
		}

		tick();
		setInterval(tick, POLL_INTERVAL_MS);
	}

	function formatBytes(bytes) {
		if (!bytes) return "0 байт";
		var units = ["байт", "KB", "MB", "GB", "TB"];
		var i = Math.min(
			Math.floor(Math.log(bytes) / Math.log(1024)),
			units.length - 1
		);
		var value = bytes / Math.pow(1024, i);
		return (i === 0 ? value : value.toFixed(1)) + " " + units[i];
	}

	function renderStreamStats(root, data) {
		var stats = data.stats;
		var live = !!(stats && stats.live);

		var badge = root.querySelector("[data-live-badge]");
		if (badge) {
			badge.textContent = live ? "в эфире" : "не в эфире";
			badge.classList.toggle("live", live);
			badge.classList.toggle("offline", !live);
		}

		var body = root.querySelector("[data-stats-body]");
		if (body) {
			if (stats === null) {
				body.innerHTML = '<p class="empty-state">Статистика недоступна.</p>';
			} else if (!stats.live) {
				body.innerHTML = '<p class="empty-state">Поток сейчас не идёт.</p>';
			} else {
				var html =
					'<div class="stats-grid">' +
					'<div class="metric"><div class="value">' +
					stats.uptime_display +
					'</div><div class="label">В эфире</div></div>' +
					'<div class="metric"><div class="value">' +
					formatBytes(stats.bytes_in) +
					'</div><div class="label">Принято (' +
					stats.bw_in +
					' bit/s)</div></div>' +
					'<div class="metric"><div class="value">' +
					formatBytes(stats.bytes_out) +
					'</div><div class="label">Отдано (' +
					stats.bw_out +
					' bit/s)</div></div>' +
					"</div>";

				if (stats.video_codec || stats.audio_codec) {
					html += '<div class="stats-grid media-info">';
					if (stats.video_codec) {
						html +=
							'<div class="metric"><div class="value">' +
							stats.video_width +
							"×" +
							stats.video_height +
							'</div><div class="label">' +
							stats.video_codec +
							(stats.video_frame_rate
								? ", " + stats.video_frame_rate + " fps"
								: "") +
							"</div></div>";
					}
					if (stats.audio_codec) {
						html +=
							'<div class="metric"><div class="value">' +
							stats.audio_codec +
							'</div><div class="label">' +
							(stats.audio_sample_rate
								? stats.audio_sample_rate + " Hz, "
								: "") +
							stats.audio_channels +
							" канал(ов)</div></div>";
					}
					html += "</div>";
				}

				body.innerHTML = html;
			}
		}

		(data.destinations || []).forEach(function (dest) {
			var slot = root.querySelector(
				'[data-destination-badge="' + dest.id + '"]'
			);
			if (!slot) return;
			if (dest.push_status === "live") {
				slot.innerHTML = '<span class="badge live">в эфире</span>';
			} else if (dest.push_status === "error") {
				slot.innerHTML = '<span class="badge error">ошибка</span>';
			} else {
				slot.innerHTML = "";
			}
		});
	}

	function pollStreamStats() {
		var root = document.querySelector("[data-stream-stats-url]");
		if (!root) return;
		var url = root.dataset.streamStatsUrl;

		function tick() {
			fetch(url, { headers: { Accept: "application/json" } })
				.then(function (r) {
					return r.ok ? r.json() : null;
				})
				.then(function (data) {
					if (!data) return;
					renderStreamStats(root, data);
				})
				.catch(function () {});
		}

		tick();
		setInterval(tick, POLL_INTERVAL_MS);
	}

	var CHAT_POLL_INTERVAL_MS = 3000;

	function pollChat() {
		var root = document.querySelector("[data-chat-url]");
		if (!root) return;
		var url = root.dataset.chatUrl;
		var container = root.querySelector("[data-chat-messages]");
		var lastId = 0;

		function tick() {
			var fetchUrl = url + (lastId ? "?after_id=" + lastId : "");
			fetch(fetchUrl, { headers: { Accept: "application/json" } })
				.then(function (r) {
					return r.ok ? r.json() : null;
				})
				.then(function (data) {
					if (!data || !data.messages.length) return;
					if (lastId === 0 && container) {
						container.innerHTML = "";
					}
					data.messages.forEach(function (message) {
						if (container) {
							var el = document.createElement("div");
							el.className = "chat-message";
							var author = document.createElement("strong");
							author.textContent = message.author_name;
							el.appendChild(author);
							el.appendChild(document.createTextNode(message.text));
							container.appendChild(el);
						}
						lastId = message.id;
					});
					if (container) container.scrollTop = container.scrollHeight;
				})
				.catch(function () {});
		}

		tick();
		setInterval(tick, CHAT_POLL_INTERVAL_MS);
	}

	document.addEventListener("DOMContentLoaded", function () {
		pollServerLoad();
		pollStreamStats();
		pollChat();
	});
})();
