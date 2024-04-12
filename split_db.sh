cd "/mnt/d/TriNetX/Encounter/"
#split -l 100000000 encounter.csv
split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv encounter.csv encounter


cd "/mnt/d/TriNetX/Diagnosis/"
split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv diagnosis.csv diagnosis

cd "/mnt/d/TriNetX/Lab Results/"
#mv lab_result.csv lab_results.csv
#split -l 100000000 lab_results.csv
split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv lab_result.csv lab_results

cd "/mnt/d/TriNetX/Medications/"
#mv medication_ingredient.csv medication.csv
#split -l 100000000 medication.csv
split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv medication_ingredient.csv medication

#cd "/mnt/d/TriNetX/Prior Diagnosis/"
#split -l 100000000 diagnosis.csv
#split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv diagnosis.csv diagnosis

cd "/mnt/d/TriNetX/Procedure/"
#split -l 100000000 procedure.csv
split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv procedure.csv procedure

cd "/mnt/d/TriNetX/Vital Signs/"
#split -l 100000000 vital_signs.csv
split -l 10000000 --numeric-suffixes=1 --suffix-length=3 --additional-suffix=.csv vital_signs.csv vital_signs