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
		if (linkField) linkField.value = preset.rtmp_link;
	});
});
