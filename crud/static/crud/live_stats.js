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

	function formatChatTime(iso) {
		var date = new Date(iso);
		if (isNaN(date.getTime())) return "";
		// Локальное время браузера зрителя, не сервера — posted_at из API
		// приходит в UTC (ISO 8601 с Z), сервер сам ничего не знает о
		// часовом поясе конкретного пользователя, только Date() в браузере.
		return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
	}

	var CHAT_POLL_INTERVAL_MS = 3000;

	function pollChat() {
		var root = document.querySelector("[data-chat-url]");
		if (!root) return;
		var url = root.dataset.chatUrl;
		var container = root.querySelector("[data-chat-messages]");
		var lastId = 0;
		var wasEnabled = null;

		function tick() {
			var fetchUrl = url + (lastId ? "?after_id=" + lastId : "");
			fetch(fetchUrl, { headers: { Accept: "application/json" } })
				.then(function (r) {
					return r.ok ? r.json() : null;
				})
				.then(function (data) {
					if (!data) return;
					if (!data.chat_enabled) {
						// Источник отключили (в этой вкладке или в другой) —
						// сбрасываем локальное состояние поллинга и то, что
						// уже нарисовано, иначе старые сообщения от прошлой
						// трансляции продолжали бы висеть на странице вечно,
						// раз новых сообщений больше не приходит и вызывать
						// перерисовку нечем.
						if (wasEnabled !== false) {
							lastId = 0;
							if (container) {
								container.innerHTML =
									'<p class="empty-state">Чат не подключён — укажите ссылку на трансляцию выше.</p>';
							}
						}
						wasEnabled = false;
						return;
					}
					wasEnabled = true;
					if (!data.messages.length) return;
					if (lastId === 0 && container) {
						container.innerHTML = "";
					}
					data.messages.forEach(function (message) {
						if (container) {
							var el = document.createElement("div");
							el.className = "chat-message";
							var time = document.createElement("span");
							time.className = "chat-time";
							time.textContent = formatChatTime(message.posted_at);
							var author = document.createElement("strong");
							author.textContent = message.author_name;
							el.appendChild(time);
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

	function pollIndexLive() {
		var root = document.querySelector("[data-index-live-url]");
		if (!root) return;
		var url = root.dataset.indexLiveUrl;

		function tick() {
			fetch(url, { headers: { Accept: "application/json" } })
				.then(function (r) {
					return r.ok ? r.json() : null;
				})
				.then(function (data) {
					if (!data || !data.available) return;
					Object.keys(data.live).forEach(function (streamId) {
						var slot = root.querySelector(
							'[data-stream-live-badge="' + streamId + '"]'
						);
						if (!slot) return;
						var live = data.live[streamId];
						slot.innerHTML = live
							? '<span class="badge live">в эфире</span>'
							: '<span class="badge offline">не в эфире</span>';
					});
				})
				.catch(function () {});
		}

		tick();
		setInterval(tick, POLL_INTERVAL_MS);
	}

	function pollLog() {
		var root = document.querySelector("[data-log-url]");
		if (!root) return;
		var url = root.dataset.logUrl;
		var body = root.querySelector("[data-log-body]");

		function tick() {
			fetch(url, { headers: { Accept: "application/json" } })
				.then(function (r) {
					return r.ok ? r.json() : null;
				})
				.then(function (data) {
					if (!data || !body) return;
					if (data.log_text === null) {
						body.innerHTML =
							'<p class="empty-state">Лога пока нет — публикации с этой дестинацией ещё не было.</p>';
					} else if (data.log_text) {
						var pre = body.querySelector(".log-view");
						if (!pre) {
							body.innerHTML = "";
							pre = document.createElement("pre");
							pre.className = "log-view";
							body.appendChild(pre);
						}
						pre.textContent = data.log_text;
					} else {
						body.innerHTML = '<p class="empty-state">Лог пуст.</p>';
					}
				})
				.catch(function () {});
		}

		tick();
		setInterval(tick, POLL_INTERVAL_MS);
	}

	document.addEventListener("DOMContentLoaded", function () {
		pollServerLoad();
		pollStreamStats();
		pollChat();
		pollIndexLive();
		pollLog();
	});
})();
