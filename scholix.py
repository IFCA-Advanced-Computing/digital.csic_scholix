#!/usr/bin/python

import sys, getopt, os
import requests
import xml.etree.ElementTree as ET
import json
import psycopg2
import re
import sqlite3

def dspace_database_query(db_user, db_password, db_host, db_port, db_database):
'''
  Search all items with its isreferenceby relation (metadata field 48)
'''
    isReferencedBy = None
    connection = None
    try:
        connection = psycopg2.connect(user = db_user,
                                      password = db_password,
                                      host = db_host,
                                      port = db_port,
                                      database = db_database)

        cursor = connection.cursor()
        postgreSQL_select_Query = "SELECT item.item_id, metadatavalue.text_value, doi.doi FROM item, metadatavalue, metadatafieldregistry, doi WHERE item.item_id = metadatavalue.item_id AND doi.resource_id =  item.item_id AND metadatavalue.metadata_field_id = metadatafieldregistry.metadata_field_id AND metadatafieldregistry.metadata_field_id = 48"

        cursor.execute(postgreSQL_select_Query)
        isReferencedBy = cursor.fetchall()

    except (Exception, psycopg2.Error) as error :
        print ("Error while fetching data from PostgreSQL", error)

    finally:
        #closing database connection.
        if(connection):
            cursor.close()
            connection.close()
            print("PostgreSQL connection is closed")
    return isReferencedBy

def check_if_updated(identifier, reference):
'''
  Checks in the internal database if the relationship has already been updated at datacite
'''
    conn = sqlite3.connect('identifiers.db')
    c = conn.cursor()
    x = c.execute("SELECT COUNT(*) FROM identifiers WHERE origin_id = '%s' and reference_id = '%s' and metadata_updated = 1" % (identifier, reference))
    result = False
    num = len(x.fetchall())
    for row in x:
        if row[0] > 0:
            result = True
    conn.close()
    return result, num

def insert_all(identifier, reference):
'''
  Insert new reference after updating in datacite in the internal database
'''
    conn = sqlite3.connect('identifiers.db')
    c = conn.cursor()
    try:
        c.execute("INSERT INTO identifiers(origin_id, reference_id, metadata_updated) VALUES ('%s', '%s', 0)" % (identifier, reference))
    except Exception as e:
        print(e)
    conn.commit()
    conn.close()

def update_updated(identifier, reference):
'''
  Update reference tagged as updated
'''
    conn = sqlite3.connect('identifiers.db')
    c = conn.cursor()
    c.execute("UPDATE identifiers SET metadata_updated = 1 WHERE origin_id = '%s' and reference_id = '%s'" % (identifier, reference))
    conn.commit()
    conn.close()

def get_metadata_xml(url,identifier,user,password):
'''
  Get the metadata from datacite, both in version 3 or 4
'''
    url = url + identifier  #DOI solver URL
    headers = {'Accept': 'application/rdf+xml'} #Type of response accpeted
    r = requests.get(url, headers=headers, auth=(user, password)) #POST with headers
    print(r.status_code)
    ns_type = 3
    if r.status_code == 200:
        with open("./temp.xml", 'wb') as f:
            f.write(r.content)
        if "http://datacite.org/schema/kernel-4" in r.text:
            ET.register_namespace('', "http://datacite.org/schema/kernel-4")
            ns_type = 4
        elif "http://datacite.org/schema/kernel-3" in r.text:
            ET.register_namespace('', "http://datacite.org/schema/kernel-3")
            ns_type = 3
        tree = ET.parse('temp.xml')
        metadata = tree.getroot()
        return metadata, ns_type
    else:
        return 'ERROR', 3

def check_related_identifiers(metadata,ns_type,id_type,related_identifier):
'''
  Checks if the relationship is already in the item datacite metadata
'''
    relation = metadata.findall('.//{http://datacite.org/schema/kernel-%i}relatedIdentifier' % ns_type)
    included = False
    counter = 0
    if len(relation) > 0:
        for elem in relation:
            print('FOUND')
            print('Counter: %i' % counter)
            counter = counter + 1
            if 'relationType' in elem.attrib:
                if elem.attrib['relationType'] == 'IsReferencedBy' and elem.text == related_identifier:
                    print('Relation is already included')
                    included = True
                else:
                    related_ids = metadata.find('{http://datacite.org/schema/kernel-%i}relatedIdentifiers' % ns_type)
                    new = ET.Element('{http://datacite.org/schema/kernel-%i}relatedIdentifier' % ns_type)
                    new.set('relationType', 'IsReferencedBy')
                    new.set('relatedIdentifierType', id_type)
                    new.text = related_identifier
                    related_ids.append(new)
            else:
                    child = ET.Element('{http://datacite.org/schema/kernel-%i}relatedIdentifiers' % ns_type)
                    grand_son = ET.Element('{http://datacite.org/schema/kernel-%i}relatedIdentifier' % ns_type)
                
                    grand_son.set('relationType', 'IsReferencedBy')
                    grand_son.set('relatedIdentifierType', id_type)
                    grand_son.text = related_identifier

                    child.append(grand_son)
                    metadata.append(child)
    else:
        child = ET.Element('{http://datacite.org/schema/kernel-%i}relatedIdentifiers' % ns_type)
        grand_son = ET.Element('{http://datacite.org/schema/kernel-%i}relatedIdentifier' % ns_type)

        grand_son.set('relationType', 'IsReferencedBy')
        grand_son.set('relatedIdentifierType', id_type)
        grand_son.text = related_identifier
        child.append(grand_son)
        metadata.append(child)

    return metadata, included


def update_metadata_xml(url,identifier,user,password,filename):
'''
  Updates de DOI metadata at datacite with the new registry
'''
    url = url + identifier  #DOI solver URL
    headers = {'Content-Type': 'application/xml'} #Type of response uploaded
    with open(filename,'rb') as payload:
        r = requests.put(url, headers=headers, auth=(user, password), data=payload) #POST with headers
        print(r.status_code)
    print('Metadata updated')

def metadata_workflow(identifier,user,password,related_identifier,id_type):
'''
  Workflow for getting, checking and update metadata
'''
    url_base = "https://mds.datacite.org/metadata/"
    result, num = check_if_updated(identifier, related_identifier)
    if result == False:
	    try:
		metadata,ns_type = get_metadata_xml(url_base,identifier,user,password)
		metadata, included = check_related_identifiers(metadata,ns_type,id_type,related_identifier)
		if included == True:
		     update_updated(identifier, related_identifier)
		else:
		    tree = ET.ElementTree(metadata)
		    filename = identifier.replace('/', '') + '_' + related_identifier.replace('/','') + '.xml'
		    tree.write(filename)
		    print("Updating metadata...")
		    os.system("cat %s" % filename)
		    update_metadata_xml(url_base,identifier,user,password,filename)
		    os.remove(filename)
	    except Exception as e:
		print("Exception: %s" % e)


def main(argv):
    user = ''
    password = ''
    try:
        opts, args = getopt.getopt(argv,"hu:p:U:P:H:T:D:",["user=","password=","db_user=","db_password=","db_host=","db_port=","db_database="])
    except getopt.GetoptError:
        print 'scholix.py -u <user> -p <password> -U <db_user> -P <db_password> -H <db_host> -T <db_port> -D <db_database>'
        sys.exit(2)
    for opt, arg in opts:
        if opt == '-h':
             print 'scholix.py -u <user> -p <password> -U <db_user> -P <db_password> -H <db_host> -T <db_port> -D <db_database>'
             sys.exit()
        elif opt in ("-u", "--user"):
            user = arg
        elif opt in ("-p", "--password"):
            password = arg
        elif opt in ("-U", "--db_user"):
            db_user = arg
        elif opt in ("-P", "--db_password"):
            db_password = arg
        elif opt in ("-H", "--db_host"):
            db_host = arg
        elif opt in ("-T", "--db_port"):
            db_port = arg
        elif opt in ("-D", "--db_database"):
            db_database = arg

    print("DB User: %s Pass: %s Host: %s Port: %s Database: %s" % (db_user, db_password, db_host, db_port, db_database))
    isReferencedBy = dspace_database_query(db_user, db_password, db_host, db_port, db_database)

    if isReferencedBy != None:
	    print("Print each row and it's columns values")
	    for row in isReferencedBy:
		#pid = re.findall(r'10+.[\d\.-]+/[\w\.-]+', row[1])
		pid = ''
		doi = ''
		doi = re.findall(r'10[\.-]+.[\d\.-]+/[\w\.-]+', row[1])
		pid = re.findall(r'handle.net+/+[\d\.-]+/[\d\.-]+', row[1])
		if len(doi) == 1:
		    print("DOI %s isReferencedBy DOI: %s\n" % (row[2],doi[0]))
                    id_type = 'DOI'
                    identifier = row[2]
                    related_identifier = doi[0]
                    result, num = check_if_updated(identifier, related_identifier)
                    if num == 0:
                        insert_all(identifier, related_identifier)
                    elif result == False:
                        metadata_workflow(identifier,user,password,related_identifier,id_type)
		elif len(pid) == 1:
		    pid = pid[0].split('/')
		    print("DOI %s isReferencedBy PID: %s/%s\n" % (row[2],pid[1],pid[2]))
                    id_type = 'Handle'
                    identifier = row[2]
                    related_identifier = "%s/%s" % (pid[1],pid[2])
                    result, num = check_if_updated(identifier, related_identifier)
                    if num == 0:
                        insert_all(identifier, related_identifier)
                    elif result == False:
                        metadata_workflow(identifier,user,password,related_identifier,id_type)

    else:
        print("Database connection problem. Nothing to update")


if __name__ == "__main__":
    main(sys.argv[1:])
