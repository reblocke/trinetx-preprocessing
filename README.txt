README

Originally written by Wayne Richards (2023)
Modified by Brian Locke (last Apr 2024)

TODO: this all could run much faster using a relational database rather than CSVs

Step 1: Download data request from TriNetX and unzip to folder.

Step 2: Place the original files in subfolders Encounter, Diagnosis, Lab Results, Medications, Vital Signs, Procedure, RFS, Final Datasets, Patient, and Master Dataset

- Medication Ingredients contains the needed information (RxNorm codes) on medications
- Prior Diagnosis and Current Diagnosis -> consolidated down to just diagnosis. (to avoid requiring duplication of the diagnosis dataset)
- Chemo_lines, genomic, medication_drug, oncology_treatment, standardized_terminology, tumor, and tumor_properties are not used. Cohort_details, datadictionary, dataset_details, manifest, and patient_cohort contain descriptions of the cohort and are also not directly used.


Step 3: To split each dataset to be small enough for handling (1 million per CSV) 

Run the following bash script: split_db.sh
* change  mnt/d/TriNetX/ to wherever you have your data stored for each split command

Step 4: Run Jupyter notebooks for each of the chunked *.csv files to pre-process (into lists of .csv files for each data element that will go into the final dataset) and discard unneeded data: Hypercapnia NEW DATA
* For each jupyter notebook, you must manually specify how many chunks from step 3 split each database into this (this behavior is to help troubleshoot in smaller chunks if you need to).
o Note: my computer has 8gb of RAM and can barely process these all.
Note: If you've got everything configured and want to run all the processing notebooks, there is a Master notebook that just runs each sub-notebook in succession.


Step 5: Run Jupyter notebooks "Hypercapnia RFS" to identify each encounter that meets one of the criteria for inclusion into the data-set.
* You additionally have to manually set the number of chunks in of each data type.

Step 6: Run Jupyter notebooks to merge the datasets into separate data sets for each reason for suspicion x setting permutation

* There is a Jupyter notebook "Hypercapnia Final Dataset Generation - Master.ipynb" where the specification for each setting and RFS can be edited at the top, or it can be passed through via an external call from the "Hypercapnia Master.ipynb" notebook.
* The number of chunks for each data-type also needs to be set for this manually for the pre-post processing.

The last step excludes encounters that do not meet the criteria of submitting at least 1 diagnosis or lab value (and thus, it needs to be pointed toward to csv files to accomplish this.

The result is output to a folder "Output" in the working directory with separate folders for AMBULATORY, EMERGENCY, and INPATIENT

In each, there is a before and after data-quality check CSV for each reason for suspicion (ABG, VBG, OBESITY, PREDISPOSITION, RESPFAIL, VENTSUPPORT)

