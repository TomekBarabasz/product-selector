import sys,argparse,re,csv
from pathlib import Path
from common import Supplier, prepareInputs,makeVerbose,LoadItems,makeTranslateSku

def loadInStockProducts(filename,encodings):
    for encoding in encodings:
        try:
            with open(filename, encoding=encoding) as csvfile:
                reader = csv.reader(csvfile)
                Products = [row[0] for row in reader if len(row)]
                return Products
        except UnicodeDecodeError:
            pass
    return []

def findDiscontinued(InStock, SupplierItems, translateSku):
    Discontinued = set()
    for sku in InStock:
        found = False
        tsku = translateSku(sku)
        for supp_name,items in SupplierItems.items():
            for name,item in items.items():
                if name==tsku:
                    found = True
                    #print(f'sku {sku} found in {supp_name}')
                    break
            if found:
                break
        if not found:
            Discontinued.add(sku)
    return Discontinued

def main(Args):
    verbose = makeVerbose(Args)
    Cfg,Suppliers = prepareInputs(Args,verbose)
    SupplierItems,_ = LoadItems(Suppliers, Cfg['encodings'], verbose)
    InStock = loadInStockProducts(Args.stock_file, Cfg['encodings'])
    print(f'Loaded {len(InStock)} InStock products')
    translateSku = makeTranslateSku(Cfg['sku_chars_to_remove'], Cfg['sku_ignore_case'])
    Discontinued = findDiscontinued(InStock, SupplierItems, translateSku)
    print(f'found {len(Discontinued)} discontinued items')
    with open(Args.output, 'w') as fout:
        for sku in Discontinued:
            fout.write(sku + '\n')
    
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("dir",type=Path,help="directory containing input (datafeed) files")
    parser.add_argument("stock_file",type=Path,help="directory containing input (datafeed) files")
    parser.add_argument("-output","-o", type=Path,help="output file path and name")
    parser.add_argument("-cfg",type=Path,help="config file path and name")
    parser.add_argument("-verbose","-v",action='store_true',help="print debug informations")
    parser.add_argument("-test","-t",action='store_true',help="run unit testing")
    Args = parser.parse_args()

    if Args.test:
        unittest.main(argv=['program_selectory.py'])
    else:
        main(Args)