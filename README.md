# product-selector
product-selector for LNRgaming ;-)

## usage
python product_selector.py arguments  

### get help:  
python product_selector.py --help  

### basic usage:  
product_selector.py datafeed_folder -cfg config.json - out output_filename  
datafeed_folder - folder with product datafeed files to be analyzed  
config.json - describes various options, some can be overwritten via command line  
  -o filename will overwrite `output_filename` from config  
  -d filename will overwrite `duplicates_filename` from config  
  -n filename will overwrite `all_skus_filename` from config  
  
## config file
### columns section
There are 3 mandatory sections: `sku`, `price` and `availability`.
For each one, list of valid titles (one for each datafeed file) can be specified.  
Additional columns, like `upc` can be specified the same way, these will be added to the output file

### replace section
In this section, for each extracted column, like `availability` value replacement rules can be specified (optionally)  
This shall address a problem with `availability` equal to `B` or `CALL` - it can be replaced with `0` or `>1`  

### suppliers section
This section defines mapping of datafeed filename to supplier name. Supplier name is required for matchig appropriate shipping cost rules
to datafeed files

### shipping_rules section
   Available rules:
      "NA" : cost    - cost to be applied when no weight is provided (weight column empty)  
      "x-ykg" : cost - cost to be applied when weight is between x and y kg  
      ">ykg"  : cost - cost to be applied when weight is more than y kg  
      "per_produce" : cost - cost to be applied per product, independent from weight
      "free" : ">x$" - free shipping above x price 

### filenames section
`output_filename` - result file  
`duplicates_filename` - file with found dulicated 'sku''s listed per row, for verification purposes [optional]  
`all_skus_filename` - file with all found `sku`'s, for verification purposes [optional]  

### sku parsing
`sku_chars_to_remove` - list of chars or symbols to be removed from the 'sku'  
   * allows matching `PRIME-B450M-K` with 'PRIME B450M-K`, both will be matched as `PRIMEB450MK`  

`sku_ignore_case` - ignores case when matching `sku`
   * allows matching `ARCHER T4E` and `Archer T4E`
  
### other
`inlude_0_priced_items` - handilng items with `price` equal to `0.0` 
  * if true, 0 priced items will be loaded and possibly appended to the output if not replaced by better duplicates
  * if false, 0 priced items are skipped
  
 
