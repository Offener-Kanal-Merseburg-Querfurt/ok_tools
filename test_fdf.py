from fdfgen import forge_fdf


# find out fields using
# pdftk ./licenses/files/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf dump_data_fields

fields = [('Markierfeld 1', True), ('Telefon', 'Hallo es geht! :)')]
fdf = forge_fdf("",fields,[],[],[])

with open("data.fdf", "wb") as fdf_file:
    fdf_file.write(fdf)

# after this, run
# pdftk ./licenses/files/2017_Antrag_Einzelgenehmigung_ausfuellbar.pdf fill_form data.fdf output output.pdfbin/
