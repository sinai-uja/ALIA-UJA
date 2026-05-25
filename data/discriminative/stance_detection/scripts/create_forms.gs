/**
 * Apps Script to generate the 60 Google Forms for the full Prolific study.
 *
 * INSTRUCTIONS:
 *   1. Upload the 60 CSVs (bloque_01.csv ... bloque_60.csv) to a folder
 *      in Google Drive named "bloques_60".
 *   2. Go to https://script.google.com and create a new project.
 *   3. Paste this code.
 *   4. Change COMPLETION_URL to your Prolific completion URL.
 *   5. Execute the functions in batches (there are 6 batches of 10):
 *        crearLote1()  -> blocks 1-10
 *        crearLote2()  -> blocks 11-20
 *        crearLote3()  -> blocks 21-30
 *        crearLote4()  -> blocks 31-40
 *        crearLote5()  -> blocks 41-50
 *        crearLote6()  -> blocks 51-60
 *   6. Check the log (View > Logs) to get the form URLs.
 *
 * It is split into batches because Apps Script has a 6-minute execution limit.
 * If a batch fails due to timeout, reduce the range.
 */

// Settings are centralized below. For the Python pipeline, see config.yaml
// in the same folder. Keep both files in sync when changing values.
var CONFIG = {
  // TODO: update these URLs before running the study
  COMPLETION_URL: "https://app.prolific.com/submissions/complete?cc=C1OCPI04",
  GUIA_URL: "https://drive.google.com/file/d/1lqUvUOaEnR2jtiH0i_EDJvbC9-eTjH3U/view?usp=sharing",
  DRIVE_FOLDER: "bloques_60",
  FORMS_FOLDER: "formularios_60",
  NUM_BLOCKS: 60,
  BATCH_SIZE: 10,
  CHOICES: ["A favor", "En contra", "Neutral"]
};

// ============================================================
// BATCHES OF 10 (execute one by one, waiting for each to finish)
// ============================================================
function crearLote1() { crearRango(1, 10); }
function crearLote2() { crearRango(11, 20); }
function crearLote3() { crearRango(21, 30); }
function crearLote4() { crearRango(31, 40); }
function crearLote5() { crearRango(41, 50); }
function crearLote6() { crearRango(51, 60); }

// If you want to create just one for testing:
function crearUnoPrueba() { crearRango(1, 1); }

// ============================================================
// CREATE FORMS FOR A RANGE OF BLOCKS
// ============================================================
function crearRango(desde, hasta) {
  var carpeta = buscarCarpeta(CONFIG.DRIVE_FOLDER);
  if (!carpeta) {
    Logger.log("ERROR: Folder '" + CONFIG.DRIVE_FOLDER + "' not found in Drive.");
    return;
  }

  var urls = [];
  for (var i = desde; i <= hasta; i++) {
    var num = i < 10 ? "0" + i : "" + i;
    var url = crearFormularioDesdeCSV("bloque_" + num + ".csv", i);
    if (url) urls.push("Block " + num + ": " + url);
  }
  Logger.log("\n=== FORM URLs ===\n" + urls.join("\n"));
}

// ============================================================
// CREATE A FORM FROM A CSV
// ============================================================
function crearFormularioDesdeCSV(nombreArchivo, numeroBloque) {
  var archivos = DriveApp.getFilesByName(nombreArchivo);
  if (!archivos.hasNext()) {
    Logger.log("ERROR: File not found: " + nombreArchivo);
    return null;
  }
  var archivo = archivos.next();
  var contenido = Utilities.parseCsv(archivo.getBlob().getDataAsString(), ';');

  if (contenido.length < 2) {
    Logger.log("ERROR: CSV " + nombreArchivo + " is empty or invalid.");
    return null;
  }

  var encabezados = contenido[0];
  var filas = contenido.slice(1);

  // Create the form
  var form = FormApp.create('Stance Detection - Block ' + (numeroBloque < 10 ? "0" + numeroBloque : numeroBloque));
  form.setDescription('Instructions and link to annotation guide: ' + CONFIG.GUIA_URL);
  form.setConfirmationMessage('Thank you for your participation. Click here to return to Prolific: ' + CONFIG.COMPLETION_URL);
  form.setCollectEmail(false);

  // Add questions
  for (var j = 0; j < filas.length; j++) {
    var fila = filas[j];
    var datos = {};
    for (var k = 0; k < encabezados.length; k++) {
      datos[encabezados[k]] = fila[k];
    }

    var pregunta = 'Target: ' + datos['target'] + '\n\nDescription: ' + datos['description'] + '\n\nComment: ' + datos['comment'];
    var item = form.addMultipleChoiceItem();
    item.setTitle(pregunta);
    item.setChoiceValues(CONFIG.CHOICES);
    item.setRequired(true);
  }

  // Move form to the specified folder
  var formFile = DriveApp.getFileById(form.getId());
  var carpetaForms = buscarCarpeta(CONFIG.FORMS_FOLDER);
  if (carpetaForms) {
    carpetaForms.addFile(formFile);
    DriveApp.getRootFolder().removeFile(formFile);
  }

  Logger.log("Created form for block " + numeroBloque + ": " + form.getPublishedUrl());
  return form.getPublishedUrl();
}

// ============================================================
// HELPER: FIND OR CREATE FOLDER
// ============================================================
function buscarCarpeta(nombre) {
  var carpetas = DriveApp.getFoldersByName(nombre);
  if (carpetas.hasNext()) {
    return carpetas.next();
  }
  return null;
}
