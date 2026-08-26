document.addEventListener("DOMContentLoaded", function () {
	var select = document.getElementById("destination-preset");
	var dataEl = document.getElementById("destination-presets-data");
	if (!select || !dataEl) return;

	var presets = JSON.parse(dataEl.textContent);

	select.addEventListener("change", function () {
		if (select.value === "") return;
		var preset = presets[parseInt(select.value, 10)];
		if (!preset) return;

		var nameField = document.getElementById("id_socialmedia_name");
		var linkField = document.getElementById("id_socialmedia_rtmp_link");
		if (nameField) nameField.value = preset.name;
		// Не у каждого пресета есть адрес (см. crud.destination_presets —
		// Rutube/VK не публикуют фиксированный) — очищаем поле и даём
		// пользователю вставить свой, а не оставляем адрес от предыдущего
		// выбранного пресета.
		if (linkField) {
			linkField.value = preset.rtmp_link || "";
			if (!preset.rtmp_link) linkField.focus();
		}
	});
});
